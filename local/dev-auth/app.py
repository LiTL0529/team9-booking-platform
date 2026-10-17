"""Local stand-in for Amazon Cognito. NOT FOR PRODUCTION.

Issues RS256 ID tokens with the same claims Cognito puts in its ID tokens
(sub, cognito:username, cognito:groups, custom:merchant_id, token_use=id) and serves
the public keys at /.well-known/jwks.json, so the services verify tokens exactly as
they do in AWS. The admin endpoints mirror AdminUpdateUserAttributes and AdminAddUserToGroup.
"""

from __future__ import annotations

import hmac
import json
import os
import threading
import time
import uuid
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Header, HTTPException
from jwt.algorithms import RSAAlgorithm
from pydantic import BaseModel, Field

ISSUER = os.environ.get("DEV_AUTH_ISSUER", "http://dev-auth:8000")
CLIENT_ID = os.environ.get("DEV_AUTH_CLIENT_ID", "local-web-client")
ADMIN_SECRET = os.environ.get("DEV_AUTH_ADMIN_SECRET", "local-admin-secret")
TOKEN_TTL = int(os.environ.get("DEV_AUTH_TOKEN_TTL", "3600"))
SEED_FILE = Path(os.environ.get("DEV_AUTH_SEED_FILE", Path(__file__).with_name("users.json")))
STATE_FILE = Path(os.environ.get("DEV_AUTH_STATE_FILE", "/tmp/dev-auth-users.json"))
MERCHANT_ROLES = {"merchant_admin", "merchant_staff"}

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_kid = uuid.uuid4().hex[:16]
_lock = threading.Lock()


def _load_users() -> dict[str, dict]:
    source = STATE_FILE if STATE_FILE.exists() else SEED_FILE
    users = json.loads(source.read_text(encoding="utf-8"))
    for name, user in users.items():
        user.setdefault("sub", str(uuid.uuid5(uuid.NAMESPACE_DNS, f"dev-auth/{name}")))
        user.setdefault("groups", ["customer"])
        user.setdefault("email", f"{name}@example.test")
    return users


_users = _load_users()


def _save() -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(_users, indent=2), encoding="utf-8")
    except OSError:
        pass


app = FastAPI(title="dev-auth (local Cognito stand-in)")


class Login(BaseModel):
    username: str
    password: str


class SignUp(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._@+-]+$")
    password: str = Field(min_length=8)
    email: str | None = None


class UserCreate(SignUp):
    groups: list[str] = ["customer"]


class MerchantRole(BaseModel):
    merchant_id: str
    role: str


def _issue(username: str, user: dict) -> dict:
    now = int(time.time())
    claims = {
        "sub": user["sub"],
        "cognito:username": username,
        "cognito:groups": user["groups"],
        "email": user["email"],
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "token_use": "id",
        "iat": now,
        "exp": now + TOKEN_TTL,
    }
    if user.get("merchant_id"):
        claims["custom:merchant_id"] = user["merchant_id"]
    token = jwt.encode(claims, _private_key, algorithm="RS256", headers={"kid": _kid})
    return {"id_token": token, "token_type": "Bearer", "expires_in": TOKEN_TTL}


def _require_admin(secret: str | None) -> None:
    if not secret or not hmac.compare_digest(secret, ADMIN_SECRET):
        raise HTTPException(status_code=403, detail="admin secret required")


@app.get("/.well-known/jwks.json")
def jwks():
    key = json.loads(RSAAlgorithm.to_jwk(_private_key.public_key()))
    key.update({"kid": _kid, "use": "sig", "alg": "RS256"})
    return {"keys": [key]}


@app.get("/.well-known/openid-configuration")
def openid_configuration():
    return {"issuer": ISSUER, "jwks_uri": f"{ISSUER}/.well-known/jwks.json"}


@app.post("/auth/login")
def login(body: Login):
    user = _users.get(body.username)
    if not user or not hmac.compare_digest(user["password"], body.password):
        raise HTTPException(status_code=401, detail="incorrect username or password")
    return _issue(body.username, user)


@app.post("/auth/signup", status_code=201)
def signup(body: SignUp):
    with _lock:
        if body.username in _users:
            raise HTTPException(status_code=409, detail="username already exists")
        _users[body.username] = {
            "password": body.password,
            "email": body.email or f"{body.username}@example.test",
            "groups": ["customer"],
            "sub": str(uuid.uuid4()),
        }
        _save()
    return {"username": body.username}


@app.post("/admin/users", status_code=201)
def admin_create_user(body: UserCreate, x_admin_secret: str | None = Header(None)):
    _require_admin(x_admin_secret)
    with _lock:
        user = _users.setdefault(body.username, {"sub": str(uuid.uuid4())})
        user.update(
            password=body.password, email=body.email or f"{body.username}@example.test", groups=body.groups
        )
        _save()
    return {"username": body.username, "sub": user["sub"]}


@app.post("/admin/users/{username}/merchant")
def admin_assign_merchant(username: str, body: MerchantRole, x_admin_secret: str | None = Header(None)):
    _require_admin(x_admin_secret)
    if body.role not in MERCHANT_ROLES:
        raise HTTPException(status_code=422, detail="unknown role")
    with _lock:
        user = _users.get(username)
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        user["merchant_id"] = body.merchant_id
        user["groups"] = sorted({g for g in user["groups"] if g not in MERCHANT_ROLES} | {body.role})
        _save()
    return {"username": username, "groups": user["groups"], "merchant_id": body.merchant_id}


@app.get("/health/live")
def live():
    return {"status": "ok"}
