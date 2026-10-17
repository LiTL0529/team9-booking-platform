import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import Settings, create_app
from platform_common.events import new_envelope
from platform_common.testing import TEST_ISSUER, TestKeys, reset_database

REPO = Path(__file__).resolve().parents[3]
CONTRACTS = REPO / "contracts"
PG = os.environ.get("TEST_PG_URL", "postgresql+psycopg://postgres:postgres@localhost:55432")
DB_URL = f"{PG}/availability_test"


class FakeCache:
    """In-memory stand-in with the same generation semantics as the Redis cache."""

    enabled = True

    def __init__(self):
        self.store, self.generations = {}, {}

    def get(self, day, parts):
        key = f"{day}:{self.generations.get(day, 0)}:{parts}"
        return key, self.store.get(key)

    def put(self, key, value):
        self.store[key] = value

    def invalidate(self, day):
        self.generations[day] = self.generations.get(day, 0) + 1


@pytest.fixture(scope="session")
def keys():
    return TestKeys()


@pytest.fixture
def ctx(keys):
    reset_database(DB_URL)
    cache = FakeCache()
    app = create_app(
        Settings(database_url=DB_URL, jwt_issuer=TEST_ISSUER), cache=cache, verifier=keys.verifier, start_background=False
    )
    with TestClient(app) as client:

        def emit(event_type, data):
            return app.state.event_processor.handle(new_envelope(event_type, data, "test"))

        yield type("Ctx", (), {"client": client, "app": app, "cache": cache, "emit": staticmethod(emit)})


def slot(merchant_id, *, resource_type="badminton_court", hours=24, name="Court 1"):
    start = (datetime.now(UTC) + timedelta(hours=hours)).replace(minute=0, second=0, microsecond=0)
    return {
        "slot_id": str(uuid.uuid4()),
        "merchant_id": merchant_id,
        "resource_id": str(uuid.uuid4()),
        "resource_name": name,
        "resource_type": resource_type,
        "start_time": start.isoformat(),
        "end_time": (start + timedelta(hours=1)).isoformat(),
        "local_date": start.date().isoformat(),
        "timezone": "Asia/Singapore",
        "capacity": 1,
    }


def booking_event(slot_data, version):
    return {
        **{k: v for k, v in slot_data.items() if k not in ("timezone", "capacity")},
        "booking_id": str(uuid.uuid4()),
        "reference": "BK-TEST0001",
        "slot_version": version,
        "customer_id": "c1",
        "customer_username": "alice",
    }
