"""Small client for the platform's public API, shared by the operational scripts.

Works against the local stack (dev-auth login) and AWS (Cognito USER_PASSWORD_AUTH).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

import httpx


@dataclass
class Config:
    gateway: str = os.environ.get("PLATFORM_GATEWAY", "http://127.0.0.1:8080")
    api_key: str = os.environ.get("PLATFORM_API_KEY", "local-web-key")
    cognito_client_id: str | None = os.environ.get("COGNITO_CLIENT_ID")
    aws_region: str = os.environ.get("AWS_REGION", "ap-southeast-1")


def login(cfg: Config, username: str, password: str) -> str:
    if cfg.cognito_client_id:
        import boto3

        result = boto3.client("cognito-idp", region_name=cfg.aws_region).initiate_auth(
            ClientId=cfg.cognito_client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )
        return result["AuthenticationResult"]["IdToken"]
    response = httpx.post(f"{cfg.gateway}/auth/login", json={"username": username, "password": password}, timeout=10)
    response.raise_for_status()
    return response.json()["id_token"]


class Api:
    def __init__(self, cfg: Config, token: str | None = None):
        headers = {"x-api-key": cfg.api_key}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.Client(base_url=cfg.gateway, headers=headers, timeout=30)

    def call(self, method: str, path: str, *, ok=(200, 201), **kwargs) -> httpx.Response:
        response = self.http.request(method, path, **kwargs)
        if response.status_code not in ok:
            raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text[:300]}")
        return response

    def book(self, slot_id: str, key: str | None = None) -> httpx.Response:
        return self.http.post(
            "/v1/bookings", json={"slot_id": slot_id}, headers={"Idempotency-Key": key or str(uuid.uuid4())}
        )
