import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import Settings, create_app
from platform_common.testing import TEST_ISSUER, TestKeys, reset_database

REPO = Path(__file__).resolve().parents[3]
CONTRACTS = REPO / "contracts"
PG = os.environ.get("TEST_PG_URL", "postgresql+psycopg://postgres:postgres@localhost:55432")
DB_URL = f"{PG}/notification_test"


@pytest.fixture(scope="session")
def keys():
    return TestKeys()


@pytest.fixture
def ctx(keys):
    reset_database(DB_URL)
    app = create_app(Settings(database_url=DB_URL, jwt_issuer=TEST_ISSUER), verifier=keys.verifier, start_background=False)
    with TestClient(app) as client:
        yield type("Ctx", (), {"client": client, "app": app})


def booking_data(customer_sub: str) -> dict:
    start = datetime.now(UTC) + timedelta(days=1)
    return {
        "booking_id": str(uuid.uuid4()),
        "reference": "BK-ABCD2345",
        "slot_id": str(uuid.uuid4()),
        "slot_version": 1,
        "customer_id": customer_sub,
        "customer_username": "alice",
        "merchant_id": str(uuid.uuid4()),
        "resource_id": str(uuid.uuid4()),
        "resource_name": "Court 1",
        "resource_type": "badminton_court",
        "start_time": start.isoformat(),
        "end_time": (start + timedelta(hours=1)).isoformat(),
        "local_date": start.date().isoformat(),
    }
