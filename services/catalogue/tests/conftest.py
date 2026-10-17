import os
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import Settings, create_app
from platform_common.messaging import InMemoryPublisher
from platform_common.testing import TEST_ISSUER, TestKeys, reset_database

REPO = Path(__file__).resolve().parents[3]
CONTRACTS = REPO / "contracts"
PG = os.environ.get("TEST_PG_URL", "postgresql+psycopg://postgres:postgres@localhost:55432")
DB_URL = f"{PG}/catalogue_test"
MERCHANT = str(uuid.uuid4())
OTHER_MERCHANT = str(uuid.uuid4())


@pytest.fixture(scope="session")
def keys():
    return TestKeys()


@pytest.fixture
def ctx(keys):
    reset_database(DB_URL)
    publisher = InMemoryPublisher()
    app = create_app(
        Settings(database_url=DB_URL, jwt_issuer=TEST_ISSUER),
        verifier=keys.verifier,
        publisher=publisher,
        start_background=False,
    )
    with TestClient(app) as client:
        yield type("Ctx", (), {"client": client, "app": app, "publisher": publisher})


@pytest.fixture
def owner(keys):
    return keys.headers("owner1", ["merchant_admin"], merchant_id=MERCHANT)


@pytest.fixture
def tomorrow():
    return date.today() + timedelta(days=1)
