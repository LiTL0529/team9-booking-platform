import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from platform_common.events import new_envelope
from platform_common.messaging import InMemoryPublisher
from platform_common.testing import TEST_ISSUER, TestKeys, reset_database

REPO = Path(__file__).resolve().parents[3]
CONTRACTS = REPO / "contracts"
PG = os.environ.get("TEST_PG_URL", "postgresql+psycopg://postgres:postgres@localhost:55432")
DB_URL = f"{PG}/booking_test"
MERCHANT = str(uuid.uuid4())


class FakeCatalogue:
    def __init__(self):
        self.slots: dict[str, dict] = {}
        self.calls = 0

    def fetch_slot(self, slot_id):
        self.calls += 1
        return self.slots.get(str(slot_id))


def slot_data(hours_from_now: float = 24, merchant_id: str = MERCHANT) -> dict:
    start = (datetime.now(UTC) + timedelta(hours=hours_from_now)).replace(microsecond=0)
    return {
        "slot_id": str(uuid.uuid4()),
        "merchant_id": merchant_id,
        "resource_id": str(uuid.uuid4()),
        "resource_name": "Court 1",
        "resource_type": "badminton_court",
        "start_time": start.isoformat(),
        "end_time": (start + timedelta(hours=1)).isoformat(),
        "local_date": start.date().isoformat(),
        "timezone": "Asia/Singapore",
        "capacity": 1,
    }


@pytest.fixture(scope="session")
def keys():
    return TestKeys()


@pytest.fixture
def ctx(keys):
    reset_database(DB_URL)
    publisher = InMemoryPublisher()
    catalogue = FakeCatalogue()
    app = create_app(
        Settings(database_url=DB_URL, jwt_issuer=TEST_ISSUER, db_pool_size=30, db_max_overflow=10),
        catalogue=catalogue,
        verifier=keys.verifier,
        publisher=publisher,
        start_background=False,
    )
    with TestClient(app) as client:

        def publish_slot(**kwargs) -> dict:
            data = slot_data(**kwargs)
            app.state.event_processor.handle(new_envelope("SlotPublished", data, "catalogue-service"))
            return data

        yield type(
            "Ctx",
            (),
            {
                "client": client,
                "app": app,
                "publisher": publisher,
                "catalogue": catalogue,
                "publish_slot": staticmethod(publish_slot),
            },
        )


@pytest.fixture
def alice(keys):
    return keys.headers("alice", ["customer"])


@pytest.fixture
def bob(keys):
    return keys.headers("bob", ["customer"])
