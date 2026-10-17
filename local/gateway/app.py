"""Local stand-in for Amazon API Gateway. NOT FOR PRODUCTION.

Does what the AWS gateway does in the target deployment:
  * routes /v1/<prefix> to the owning microservice
  * requires an API key per client application, with a per-key usage plan (rate + burst)
  * checks bearer tokens on protected routes (the services check them again themselves)
  * load-balances across every replica of a service (docker compose --scale)
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
import jwt
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s gateway %(levelname)s %(message)s")
log = logging.getLogger("gateway")

ROUTES: list[tuple[str, str]] = [
    (prefix, url)
    for prefix, url in json.loads(
        os.environ.get(
            "GATEWAY_ROUTES",
            json.dumps(
                [
                    ["/v1/merchants", "http://merchant:8000"],
                    ["/v1/resources", "http://catalogue:8000"],
                    ["/v1/slots", "http://catalogue:8000"],
                    ["/v1/availability", "http://availability:8000"],
                    ["/v1/bookings", "http://booking:8000"],
                    ["/v1/notifications", "http://notification:8000"],
                    ["/auth", "http://dev-auth:8000"],
                ]
            ),
        )
    )
]
# Mirrors the API Gateway method settings: these are reachable with an API key only.
PUBLIC_PREFIXES = ("/v1/availability", "/v1/slots", "/auth")
PUBLIC_GET_PREFIXES = ("/v1/resources",)
NO_API_KEY_PREFIXES = ("/auth",)
JWKS_URL = os.environ.get("GATEWAY_JWKS_URL", "http://dev-auth:8000/.well-known/jwks.json")
ISSUER = os.environ.get("GATEWAY_JWT_ISSUER", "http://dev-auth:8000")
API_KEYS: dict[str, dict] = json.loads(
    os.environ.get(
        "GATEWAY_API_KEYS",
        json.dumps(
            {
                "local-web-key": {"client": "web", "rate": 300, "burst": 600},
                "local-partner-key": {"client": "partner-demo", "rate": 10, "burst": 20},
                "local-loadtest-key": {"client": "load-test", "rate": 5000, "burst": 5000},
            }
        ),
    )
)
HOP_HEADERS = {"connection", "keep-alive", "transfer-encoding", "te", "upgrade", "host", "content-length"}


@dataclass
class TokenBucket:
    rate: float
    burst: float
    tokens: float = field(init=False)
    updated: float = field(default_factory=time.monotonic)

    def __post_init__(self):
        self.tokens = self.burst

    def take(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class Upstream:
    """Round-robin over all IPs behind a service name, refreshed every few seconds."""

    def __init__(self, base_url: str):
        parts = urlsplit(base_url)
        self.scheme, self.host, self.port = parts.scheme, parts.hostname, parts.port or 80
        self._ips: list[str] = []
        self._cycle = itertools.cycle([self.host])
        self._resolved_at = 0.0

    def next_base(self) -> str:
        if time.monotonic() - self._resolved_at > 5:
            try:
                infos = socket.getaddrinfo(self.host, self.port, family=socket.AF_INET, type=socket.SOCK_STREAM)
                ips = sorted({info[4][0] for info in infos})
            except socket.gaierror:
                ips = []
            if ips and ips != self._ips:
                log.info("upstream %s -> %s", self.host, ips)
                self._ips = ips
                self._cycle = itertools.cycle(ips)
            self._resolved_at = time.monotonic()
        return f"{self.scheme}://{next(self._cycle)}:{self.port}"


app = FastAPI(title="Local API gateway", docs_url=None, redoc_url=None)
buckets = {key: TokenBucket(cfg["rate"], cfg["burst"]) for key, cfg in API_KEYS.items()}
upstreams = {prefix: Upstream(url) for prefix, url in ROUTES}
jwks_client = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=300)
client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=3.0), limits=httpx.Limits(max_connections=500))


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _route(path: str) -> str | None:
    for prefix, _ in ROUTES:
        if path == prefix or path.startswith(prefix + "/"):
            return prefix
    return None


@app.get("/gateway/health")
async def health():
    return {"status": "ok"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(path: str, request: Request):
    full_path = "/" + path
    prefix = _route(full_path)
    if prefix is None:
        return error(404, "no_route", f"no route for {full_path}")

    client_name = "anonymous"
    if not prefix.startswith(NO_API_KEY_PREFIXES):
        key = request.headers.get("x-api-key")
        if key not in API_KEYS:
            return error(403, "forbidden", "missing or invalid API key")
        if not buckets[key].take():
            return error(429, "too_many_requests", "rate limit exceeded for this API key")
        client_name = API_KEYS[key]["client"]

    is_public = prefix.startswith(PUBLIC_PREFIXES) or (
        request.method == "GET" and prefix.startswith(PUBLIC_GET_PREFIXES)
    )
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
        try:
            signing_key = await asyncio.to_thread(jwks_client.get_signing_key_from_jwt, token)
            jwt.decode(token, signing_key.key, algorithms=["RS256"], issuer=ISSUER, options={"verify_aud": False})
        except jwt.PyJWTError:
            return error(401, "unauthorized", "invalid or expired token")
    elif not is_public:
        return error(401, "unauthorized", "bearer token required")

    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
    headers["x-request-id"] = request.headers.get("x-request-id") or str(uuid.uuid4())
    headers["x-api-client"] = client_name
    url = upstreams[prefix].next_base() + full_path
    try:
        upstream = await client.request(
            request.method, url, params=request.query_params, content=await request.body(), headers=headers
        )
    except httpx.TimeoutException:
        return error(504, "gateway_timeout", f"{prefix} did not respond in time")
    except httpx.TransportError:
        return error(503, "service_unavailable", f"{prefix} is unavailable")
    response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP_HEADERS | {"content-encoding"}}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)
