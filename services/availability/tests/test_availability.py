import uuid

from conftest import CONTRACTS, booking_event, slot

from platform_common.testing import assert_openapi_matches


def search(ctx, day, **params):
    response = ctx.client.get("/v1/availability/slots", params={"date": day, **params})
    assert response.status_code == 200, response.text
    return response


def test_search_across_merchants_with_filters(ctx):
    m1, m2 = str(uuid.uuid4()), str(uuid.uuid4())
    ctx.emit("MerchantOnboarded", {"merchant_id": m1, "name": "Alpha", "slug": "alpha", "contact_email": "a@a.test"})
    ctx.emit("MerchantOnboarded", {"merchant_id": m2, "name": "Beta", "slug": "beta", "contact_email": "b@b.test"})
    s1 = slot(m1)
    ctx.emit("SlotPublished", s1)
    ctx.emit("SlotPublished", slot(m2, resource_type="tennis_court"))
    day = s1["local_date"]
    assert search(ctx, day).json()["count"] == 2
    filtered = search(ctx, day, merchant_id=m1).json()
    assert [s["merchant_name"] for s in filtered["slots"]] == ["Alpha"]
    assert search(ctx, day, resource_type="tennis_court").json()["count"] == 1
    assert ctx.client.get("/v1/availability/resource-types").json() == ["badminton_court", "tennis_court"]
    assert [m["slug"] for m in ctx.client.get("/v1/availability/merchants").json()] == ["alpha", "beta"]


def test_booked_slot_disappears_and_returns_after_cancellation(ctx):
    s = slot(str(uuid.uuid4()))
    ctx.emit("SlotPublished", s)
    ctx.emit("BookingConfirmed", booking_event(s, 1))
    assert search(ctx, s["local_date"]).json()["count"] == 0
    assert search(ctx, s["local_date"], include_booked=True).json()["slots"][0]["status"] == "BOOKED"
    ctx.emit("BookingCancelled", {**booking_event(s, 2), "cancelled_at": s["start_time"]})
    assert search(ctx, s["local_date"]).json()["count"] == 1


def test_out_of_order_events_converge(ctx):
    s = slot(str(uuid.uuid4()))
    ctx.emit("BookingCancelled", {**booking_event(s, 2), "cancelled_at": s["start_time"]})
    ctx.emit("BookingConfirmed", booking_event(s, 1))  # older event arrives late
    ctx.emit("SlotPublished", s)  # slot details arrive last
    result = search(ctx, s["local_date"]).json()
    assert result["count"] == 1
    assert result["slots"][0]["status"] == "AVAILABLE"


def test_cache_hit_and_invalidation_on_events(ctx):
    s = slot(str(uuid.uuid4()))
    ctx.emit("SlotPublished", s)
    day = s["local_date"]
    assert search(ctx, day).headers["X-Cache"] == "MISS"
    assert search(ctx, day).headers["X-Cache"] == "HIT"
    ctx.emit("BookingConfirmed", booking_event(s, 1))
    response = search(ctx, day)
    assert response.headers["X-Cache"] == "MISS"
    assert response.json()["count"] == 0


def test_search_requires_a_date(ctx):
    assert ctx.client.get("/v1/availability/slots").status_code == 422


def test_openapi_matches_committed_contract(ctx):
    assert_openapi_matches(ctx.app, CONTRACTS / "openapi" / "availability.json")
