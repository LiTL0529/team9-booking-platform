import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.identity import NullDirectory
from app.main import create_app
from platform_common.messaging import InMemoryPublisher
from platform_common.testing import TEST_ISSUER, TestKeys, reset_database

REPO = Path(__file__).resolve().parents[3]
CONTRACTS = REPO / "contracts"
PG = os.environ.get("TEST_PG_URL", "postgresql+psycopg://postgres:postgres@localhost:55432")
DB_URL = f"{PG}/merchant_test"


@pytest.fixture(scope="session")
def keys():
    return TestKeys()


@pytest.fixture
def ctx(keys):
    reset_database(DB_URL)
    publisher = InMemoryPublisher()
    identity = NullDirectory()
    app = create_app(
        Settings(database_url=DB_URL, jwt_issuer=TEST_ISSUER),
        identity=identity,
        verifier=keys.verifier,
        publisher=publisher,
        start_background=False,
    )
    with TestClient(app) as client:
        yield type("Ctx", (), {"client": client, "app": app, "publisher": publisher, "identity": identity})


@pytest.fixture
def admin(keys):
    return keys.headers("admin", ["platform_admin"])
