"""Token checks shared by every service.

Each service verifies the bearer token itself instead of trusting the gateway alone.
Tokens are Cognito ID tokens in AWS and dev-auth tokens locally; both carry the same
claims, so the services do not need to know which one issued them.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .errors import Forbidden, Unauthorized

PLATFORM_ADMIN = "platform_admin"
MERCHANT_ADMIN = "merchant_admin"
MERCHANT_STAFF = "merchant_staff"
CUSTOMER = "customer"
MERCHANT_ROLES = frozenset({MERCHANT_ADMIN, MERCHANT_STAFF})

GROUPS_CLAIM = "cognito:groups"
USERNAME_CLAIM = "cognito:username"
MERCHANT_CLAIM = "custom:merchant_id"


@dataclass(frozen=True)
class Principal:
    sub: str
    username: str
    email: str | None = None
    groups: frozenset[str] = field(default_factory=frozenset)
    merchant_id: str | None = None

    @property
    def is_platform_admin(self) -> bool:
        return PLATFORM_ADMIN in self.groups

    @property
    def is_customer(self) -> bool:
        return CUSTOMER in self.groups

    def is_member_of(self, merchant_id: object) -> bool:
        return (
            self.merchant_id is not None
            and str(merchant_id) == self.merchant_id
            and bool(self.groups & MERCHANT_ROLES)
        )

    def can_manage_merchant(self, merchant_id: object) -> bool:
        return self.is_platform_admin or self.is_member_of(merchant_id)

    @classmethod
    def from_claims(cls, claims: dict) -> Principal:
        groups = claims.get(GROUPS_CLAIM) or []
        if isinstance(groups, str):
            groups = [groups]
        return cls(
            sub=str(claims["sub"]),
            username=str(claims.get(USERNAME_CLAIM) or claims.get("username") or claims["sub"]),
            email=claims.get("email"),
            groups=frozenset(groups),
            merchant_id=claims.get(MERCHANT_CLAIM) or None,
        )


class TokenVerifier:
    """Verifies RS256 tokens against the identity provider's JWKS endpoint."""

    def __init__(self, jwks_url: str, issuer: str, audience: str | None = None):
        self._jwks = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=300, timeout=5)
        self._issuer = issuer
        # Comma-separated list of accepted app client IDs (web app, partner client, ...)
        self._audience = [a.strip() for a in audience.split(",") if a.strip()] if audience else None

    def _key_for(self, token: str):
        return self._jwks.get_signing_key_from_jwt(token).key

    def verify(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._key_for(token),
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iat", "sub"], "verify_aud": self._audience is not None},
            )
        except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
            raise Unauthorized(f"invalid token: {exc}") from exc
        if claims.get("token_use") not in (None, "id"):
            raise Unauthorized("an ID token is required")
        return Principal.from_claims(claims)


class StaticKeyVerifier(TokenVerifier):
    """Verifier with a fixed public key; used by tests."""

    def __init__(self, public_key, issuer: str, audience: str | None = None):
        self._public_key = public_key
        self._issuer = issuer
        self._audience = audience

    def _key_for(self, token: str):
        return self._public_key


_bearer = HTTPBearer(auto_error=False)


def optional_principal(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> Principal | None:
    if credentials is None:
        return None
    return request.app.state.verifier.verify(credentials.credentials)


def current_principal(principal: Principal | None = Depends(optional_principal)) -> Principal:
    if principal is None:
        raise Unauthorized("missing bearer token")
    return principal


def require_any_role(*roles: str):
    wanted = frozenset(roles)

    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.groups & wanted:
            raise Forbidden(f"requires one of the roles: {', '.join(sorted(wanted))}")
        return principal

    return dependency


def ensure_can_manage_merchant(principal: Principal, merchant_id: object) -> None:
    if not principal.can_manage_merchant(merchant_id):
        raise Forbidden("you are not a member of this merchant")


def roles_of(groups: Iterable[str]) -> list[str]:
    return sorted(set(groups))
