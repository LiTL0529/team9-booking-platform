"""End-to-end smoke test, run by every pipeline after a deployment and usable locally.

Walks the whole customer workflow through the gateway and checks the security rules:
search -> book -> conflict for a second customer -> notification -> cancel -> slot free again.

  python tests/e2e/smoke_test.py
"""

from __future__ import annotations

import os
import random
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from platform_client import Api, Config, login  # noqa: E402

PASSWORD = os.environ.get("SMOKE_PASSWORD", "Passw0rd!")


def eventually(fn, what: str, timeout: float = 30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(1)
    raise AssertionError(f"timed out waiting for {what}")


def reserve_slot(public, customer, first: int):
    """Concurrent pipelines can race on a search snapshot; retry only a real 409."""
    conflicts = 0
    for offset in range(first, first + 14):
        day = (date.today() + timedelta(days=offset)).isoformat()
        slots = public.call("GET", "/v1/availability/slots", params={"date": day}).json()["slots"]
        random.SystemRandom().shuffle(slots)
        for slot in slots[:10]:
            key = str(uuid.uuid4())
            booking = customer.book(slot["slot_id"], key)
            if booking.status_code == 409:
                conflicts += 1
                continue
            assert booking.status_code == 201, booking.text
            print(f"1. reserved a slot on {day}; concurrent conflicts retried: {conflicts}")
            return day, slot, key, booking
    raise AssertionError(f"No reservable slot in 14 days; conflicts={conflicts}; prepare future inventory")


def main() -> None:
    cfg = Config()
    public = Api(cfg)
    alice = Api(cfg, login(cfg, os.environ.get("SMOKE_USER_A", "alice"), PASSWORD))
    bob = Api(cfg, login(cfg, os.environ.get("SMOKE_USER_B", "bob"), PASSWORD))

    # Security controls at the edge
    today = date.today().isoformat()
    assert httpx.get(f"{cfg.gateway}/v1/availability/slots", params={"date": today}).status_code == 403, "API key"
    assert public.http.get("/v1/bookings").status_code == 401, "token required"

    # Start at SMOKE_DAYS_AHEAD and walk forward: load tests may have booked out the nearest days.
    first = int(os.environ.get("SMOKE_DAYS_AHEAD", "1"))
    day, slot, key, booking = reserve_slot(public, alice, first)
    replay = alice.book(slot["slot_id"], key)
    assert replay.status_code == 200 and replay.json()["booking_id"] == booking.json()["booking_id"]
    print(f"2. booked {booking.json()['reference']}; retry with the same key returned the same booking")

    assert bob.book(slot["slot_id"]).status_code == 409
    booking_id = booking.json()["booking_id"]
    assert bob.http.get(f"/v1/bookings/{booking_id}").status_code == 403
    assert bob.http.post(f"/v1/bookings/{booking_id}/cancel").status_code == 403
    print("3. second customer got 409 and cannot read or cancel the first customer's booking")

    eventually(
        lambda: not any(
            s["slot_id"] == slot["slot_id"]
            for s in public.call("GET", "/v1/availability/slots", params={"date": day}).json()["slots"]
        ),
        "slot to disappear from search",
    )
    reference = booking.json()["reference"]
    eventually(
        lambda: any(reference in n["title"] for n in alice.call("GET", "/v1/notifications").json()),
        "confirmation notification",
    )
    print("4. search updated from events and the confirmation reached the inbox")

    assert alice.call("POST", f"/v1/bookings/{booking_id}/cancel").json()["status"] == "CANCELLED"
    eventually(
        lambda: any(
            s["slot_id"] == slot["slot_id"]
            for s in public.call("GET", "/v1/availability/slots", params={"date": day}).json()["slots"]
        ),
        "slot to become available again",
    )
    print("5. cancellation released the slot")
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
