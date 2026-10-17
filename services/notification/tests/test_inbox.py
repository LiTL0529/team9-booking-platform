from conftest import CONTRACTS, booking_data

from platform_common.events import new_envelope
from platform_common.testing import assert_openapi_matches


def test_confirmation_lands_in_customer_inbox_once(ctx, keys):
    envelope = new_envelope("BookingConfirmed", booking_data("sub-alice"), "booking-service")
    processor = ctx.app.state.event_processor
    assert processor.handle(envelope) is True
    assert processor.handle(envelope) is False  # redelivery is ignored
    alice = keys.headers("alice", ["customer"])
    inbox = ctx.client.get("/v1/notifications", headers=alice).json()
    assert len(inbox) == 1
    assert inbox[0]["kind"] == "BOOKING_CONFIRMED"
    assert "BK-ABCD2345" in inbox[0]["title"]


def test_customers_only_see_their_own_notifications(ctx, keys):
    ctx.app.state.event_processor.handle(new_envelope("BookingConfirmed", booking_data("sub-alice"), "b"))
    bob = keys.headers("bob", ["customer"])
    assert ctx.client.get("/v1/notifications", headers=bob).json() == []
    alice = keys.headers("alice", ["customer"])
    notification_id = ctx.client.get("/v1/notifications", headers=alice).json()[0]["notification_id"]
    assert ctx.client.post(f"/v1/notifications/{notification_id}/read", headers=bob).status_code == 404


def test_mark_read_updates_unread_count(ctx, keys):
    data = booking_data("sub-alice")
    ctx.app.state.event_processor.handle(new_envelope("BookingConfirmed", data, "b"))
    ctx.app.state.event_processor.handle(new_envelope("BookingCancelled", {**data, "cancelled_at": data["start_time"]}, "b"))
    alice = keys.headers("alice", ["customer"])
    assert ctx.client.get("/v1/notifications/unread-count", headers=alice).json() == {"unread": 2}
    first = ctx.client.get("/v1/notifications", headers=alice).json()[0]
    assert first["kind"] == "BOOKING_CANCELLED"
    ctx.client.post(f"/v1/notifications/{first['notification_id']}/read", headers=alice)
    assert ctx.client.get("/v1/notifications/unread-count", headers=alice).json() == {"unread": 1}


def test_inbox_requires_authentication(ctx):
    assert ctx.client.get("/v1/notifications").status_code == 401


def test_openapi_matches_committed_contract(ctx):
    assert_openapi_matches(ctx.app, CONTRACTS / "openapi" / "notification.json")
