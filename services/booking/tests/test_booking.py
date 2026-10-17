import uuid
from concurrent.futures import ThreadPoolExecutor

from conftest import CONTRACTS, MERCHANT, slot_data

from app import domain
from platform_common.auth import Principal
from platform_common.errors import Conflict
from platform_common.events import new_envelope
from platform_common.testing import assert_openapi_matches, assert_valid_event


def book(ctx, headers, slot_id, key=None):
    return ctx.client.post(
        "/v1/bookings", json={"slot_id": slot_id}, headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())}
    )


def test_customer_books_available_slot_and_event_is_staged(ctx, alice):
    slot = ctx.publish_slot()
    response = book(ctx, alice, slot["slot_id"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "CONFIRMED"
    assert body["reference"].startswith("BK-")
    ctx.app.state.relay.drain_all()
    [event] = ctx.publisher.of_type("BookingConfirmed")
    assert event["data"]["slot_version"] == 1
    assert_valid_event(event, CONTRACTS)


def test_second_customer_gets_conflict(ctx, alice, bob):
    slot = ctx.publish_slot()
    assert book(ctx, alice, slot["slot_id"]).status_code == 201
    response = book(ctx, bob, slot["slot_id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slot_taken"


def test_retry_with_same_idempotency_key_returns_original_booking(ctx, alice):
    slot = ctx.publish_slot()
    first = book(ctx, alice, slot["slot_id"], key="retry-key-0001")
    again = book(ctx, alice, slot["slot_id"], key="retry-key-0001")
    assert first.status_code == 201
    assert again.status_code == 200
    assert again.headers["Idempotent-Replay"] == "true"
    assert again.json()["booking_id"] == first.json()["booking_id"]
    ctx.app.state.relay.drain_all()
    assert len(ctx.publisher.of_type("BookingConfirmed")) == 1


def test_idempotency_key_cannot_be_reused_for_another_slot(ctx, alice):
    first, second = ctx.publish_slot(), ctx.publish_slot(hours_from_now=30)
    book(ctx, alice, first["slot_id"], key="same-key-0001")
    assert book(ctx, alice, second["slot_id"], key="same-key-0001").status_code == 422


def test_idempotency_key_header_is_required(ctx, alice):
    slot = ctx.publish_slot()
    assert ctx.client.post("/v1/bookings", json={"slot_id": slot["slot_id"]}, headers=alice).status_code == 422


def test_only_customers_can_book(ctx, keys):
    slot = ctx.publish_slot()
    staff = keys.headers("staff", ["merchant_staff"], merchant_id=MERCHANT)
    assert book(ctx, staff, slot["slot_id"]).status_code == 403
    assert ctx.client.post("/v1/bookings", json={"slot_id": slot["slot_id"]}).status_code == 401


def test_slot_in_the_past_cannot_be_booked(ctx, alice):
    slot = ctx.publish_slot(hours_from_now=-2)
    assert book(ctx, alice, slot["slot_id"]).status_code == 422


def test_cancel_releases_slot_for_another_customer(ctx, alice, bob):
    slot = ctx.publish_slot()
    booking = book(ctx, alice, slot["slot_id"]).json()
    cancelled = ctx.client.post(f"/v1/bookings/{booking['booking_id']}/cancel", headers=alice)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert book(ctx, bob, slot["slot_id"]).status_code == 201
    ctx.app.state.relay.drain_all()
    [event] = ctx.publisher.of_type("BookingCancelled")
    assert event["data"]["slot_version"] == 2
    assert_valid_event(event, CONTRACTS)


def test_customer_cannot_cancel_someone_elses_booking(ctx, alice, bob):
    slot = ctx.publish_slot()
    booking = book(ctx, alice, slot["slot_id"]).json()
    assert ctx.client.post(f"/v1/bookings/{booking['booking_id']}/cancel", headers=bob).status_code == 403
    assert ctx.client.get(f"/v1/bookings/{booking['booking_id']}", headers=bob).status_code == 403


def test_double_cancel_is_rejected(ctx, alice):
    slot = ctx.publish_slot()
    booking = book(ctx, alice, slot["slot_id"]).json()
    ctx.client.post(f"/v1/bookings/{booking['booking_id']}/cancel", headers=alice)
    assert ctx.client.post(f"/v1/bookings/{booking['booking_id']}/cancel", headers=alice).status_code == 409


def test_customers_see_only_their_own_bookings(ctx, alice, bob):
    book(ctx, alice, ctx.publish_slot()["slot_id"])
    book(ctx, bob, ctx.publish_slot(hours_from_now=30)["slot_id"])
    mine = ctx.client.get("/v1/bookings", headers=alice).json()
    assert [b["customer_username"] for b in mine] == ["alice"]


def test_merchant_sees_only_own_merchant_bookings(ctx, alice, keys):
    other_merchant = str(uuid.uuid4())
    book(ctx, alice, ctx.publish_slot()["slot_id"])
    book(ctx, alice, ctx.publish_slot(merchant_id=other_merchant)["slot_id"])
    staff = keys.headers("staff", ["merchant_staff"], merchant_id=MERCHANT)
    listed = ctx.client.get("/v1/bookings", params={"merchant_id": MERCHANT}, headers=staff).json()
    assert len(listed) == 1 and listed[0]["merchant_id"] == MERCHANT
    assert ctx.client.get("/v1/bookings", params={"merchant_id": other_merchant}, headers=staff).status_code == 403


def test_unknown_slot_is_read_through_from_catalogue(ctx, alice):
    data = slot_data()
    ctx.catalogue.slots[data["slot_id"]] = data
    assert book(ctx, alice, data["slot_id"]).status_code == 201
    assert ctx.catalogue.calls == 1
    assert book(ctx, alice, str(uuid.uuid4())).status_code == 404


def test_late_slot_published_event_does_not_reset_a_booked_slot(ctx, alice, bob):
    slot = ctx.publish_slot()
    book(ctx, alice, slot["slot_id"])
    ctx.app.state.event_processor.handle(new_envelope("SlotPublished", slot, "catalogue-service"))
    assert book(ctx, bob, slot["slot_id"]).status_code == 409


def test_duplicate_event_is_processed_once(ctx):
    envelope = new_envelope("SlotPublished", slot_data(), "catalogue-service")
    assert ctx.app.state.event_processor.handle(envelope) is True
    assert ctx.app.state.event_processor.handle(envelope) is False


def test_concurrent_requests_for_one_slot_produce_exactly_one_booking(ctx):
    """Many customers race for one slot through separate sessions and connections."""
    slot = ctx.publish_slot()
    db = ctx.app.state.db

    def attempt(i: int) -> str:
        principal = Principal(sub=f"cust-{i}", username=f"cust-{i}", groups=frozenset({"customer"}))
        with db.session() as session:
            try:
                domain.create_booking(session, principal, uuid.UUID(slot["slot_id"]), f"key-{i:08d}", ctx.catalogue)
                return "booked"
            except Conflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=25) as pool:
        results = list(pool.map(attempt, range(50)))
    assert results.count("booked") == 1
    assert results.count("conflict") == 49


def test_openapi_matches_committed_contract(ctx):
    assert_openapi_matches(ctx.app, CONTRACTS / "openapi" / "booking.json")
