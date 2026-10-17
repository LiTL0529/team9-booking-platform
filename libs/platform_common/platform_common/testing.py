"""Helpers shared by the service test suites."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from .auth import GROUPS_CLAIM, MERCHANT_CLAIM, USERNAME_CLAIM, StaticKeyVerifier

TEST_ISSUER = "https://issuer.test"


class TestKeys:
    __test__ = False  # not a pytest class

    def __init__(self) -> None:
        self._private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.verifier = StaticKeyVerifier(self._private.public_key(), TEST_ISSUER)

    def token(
        self,
        username: str,
        groups: list[str],
        merchant_id: str | None = None,
        *,
        sub: str | None = None,
        expires_in: int = 3600,
    ) -> str:
        now = int(time.time())
        claims = {
            "sub": sub or f"sub-{username}",
            USERNAME_CLAIM: username,
            "email": f"{username}@example.test",
            GROUPS_CLAIM: groups,
            "iss": TEST_ISSUER,
            "iat": now,
            "exp": now + expires_in,
            "token_use": "id",
            "jti": str(uuid.uuid4()),
        }
        if merchant_id:
            claims[MERCHANT_CLAIM] = merchant_id
        return jwt.encode(claims, self._private, algorithm="RS256")

    def headers(self, *args, **kwargs) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(*args, **kwargs)}"}


def assert_valid_event(envelope: dict, contracts_dir: Path) -> None:
    """Contract test: the event must match the published envelope and data schemas."""
    import jsonschema

    schemas = contracts_dir / "events"
    envelope_schema = json.loads((schemas / "envelope.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(envelope, envelope_schema)
    data_schema = json.loads((schemas / f"{envelope['event_type']}.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(envelope["data"], data_schema)


def assert_openapi_matches(app, spec_path: Path) -> None:
    """Contract test: the running API must match the committed OpenAPI document.

    Regenerate with `python scripts/export_openapi.py` after an intentional change, so that
    every API change shows up in review as a diff of the contract.
    """
    committed = json.loads(spec_path.read_text(encoding="utf-8"))
    actual = json.loads(json.dumps(app.openapi()))
    for spec in (committed, actual):  # the build version is not part of the contract
        spec.get("info", {}).pop("version", None)
    assert actual == committed, f"{spec_path.name} is out of date; run scripts/export_openapi.py"


def reset_database(url: str) -> None:
    """Create the test database if needed and drop everything in it."""
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target.database}).first()
        if not exists:
            conn.exec_driver_sql(f'CREATE DATABASE "{target.database}"')
    admin.dispose()
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    engine.dispose()
