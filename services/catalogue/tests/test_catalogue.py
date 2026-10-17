from datetime import timedelta

from conftest import CONTRACTS, MERCHANT, OTHER_MERCHANT

from platform_common.testing import assert_openapi_matches, assert_valid_event


def create_court(ctx, headers, name="Court 1"):
    response = ctx.client.post("/v1/resources", json={"name": name, "resource_type": "badminton_court"}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def publish(ctx, headers, resource_id, day, start=8, end=12, **extra):
    body = {"from_date": day.isoformat(), "to_date": day.isoformat(), "start_hour": start, "end_hour": end, **extra}
    return ctx.client.post(f"/v1/resources/{resource_id}/slots", json=body, headers=headers)


def test_merchant_creates_resource_for_own_merchant(ctx, owner):
    court = create_court(ctx, owner)
    assert court["merchant_id"] == MERCHANT
    listed = ctx.client.get("/v1/resources", params={"merchant_id": MERCHANT}).json()
    assert [r["name"] for r in listed] == ["Court 1"]


def test_merchant_cannot_create_resource_for_another_merchant(ctx, owner):
    response = ctx.client.post(
        "/v1/resources",
        json={"merchant_id": OTHER_MERCHANT, "name": "X", "resource_type": "badminton_court"},
        headers=owner,
    )
    assert response.status_code == 403


def test_publish_one_hour_slots_emits_one_event_per_slot(ctx, owner, tomorrow):
    court = create_court(ctx, owner)
    response = publish(ctx, owner, court["resource_id"], tomorrow, 8, 12)
    assert response.status_code == 201
    assert response.json()["created"] == 4
    ctx.app.state.relay.drain_all()
    events = ctx.publisher.of_type("SlotPublished")
    assert len(events) == 4
    for event in events:
        assert_valid_event(event, CONTRACTS)
    first = events[0]["data"]
    assert first["resource_name"] == "Court 1"
    assert first["local_date"] == tomorrow.isoformat()


def test_overlapping_slots_are_rejected_unless_skipped(ctx, owner, tomorrow):
    court = create_court(ctx, owner)
    publish(ctx, owner, court["resource_id"], tomorrow, 8, 10)
    clash = publish(ctx, owner, court["resource_id"], tomorrow, 9, 12)
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "slot_overlap"
    skipped = publish(ctx, owner, court["resource_id"], tomorrow, 9, 12, skip_existing=True)
    assert skipped.status_code == 201
    assert skipped.json()["created"] == 2
    assert skipped.json()["skipped_existing"] == 1


def test_same_hours_on_different_resources_are_allowed(ctx, owner, tomorrow):
    a = create_court(ctx, owner, "A")
    b = create_court(ctx, owner, "B")
    assert publish(ctx, owner, a["resource_id"], tomorrow).status_code == 201
    assert publish(ctx, owner, b["resource_id"], tomorrow).status_code == 201


def test_database_constraint_blocks_overlap_even_without_service_check(ctx, owner, tomorrow):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    court = create_court(ctx, owner)
    publish(ctx, owner, court["resource_id"], tomorrow, 8, 9)
    slot = ctx.client.get(f"/v1/resources/{court['resource_id']}/slots").json()[0]
    insert = text(
        "INSERT INTO time_slots (slot_id, resource_id, merchant_id, start_time, end_time, local_date) "
        "VALUES (gen_random_uuid(), :r, :m, (:s)::timestamptz + (:shift)::interval, "
        "(:s)::timestamptz + (:shift)::interval + interval '1 hour', :d)"
    )
    # same hour, and a half-hour offset that would partially overlap
    for shift in ("0 minutes", "30 minutes"):
        with ctx.app.state.db.engine.connect() as conn:
            try:
                conn.execute(
                    insert,
                    {"r": court["resource_id"], "m": MERCHANT, "s": slot["start_time"], "d": tomorrow, "shift": shift},
                )
                raise AssertionError(f"overlap with shift {shift} should have been rejected")
            except IntegrityError:
                pass


def test_past_dates_are_rejected(ctx, owner, tomorrow):
    court = create_court(ctx, owner)
    response = publish(ctx, owner, court["resource_id"], tomorrow - timedelta(days=3))
    assert response.status_code == 422


def test_slot_detail_is_public(ctx, owner, tomorrow):
    court = create_court(ctx, owner)
    slot_id = publish(ctx, owner, court["resource_id"], tomorrow, 8, 9).json()["slots"][0]["slot_id"]
    detail = ctx.client.get(f"/v1/slots/{slot_id}")
    assert detail.status_code == 200
    assert detail.json()["resource_type"] == "badminton_court"


def test_openapi_matches_committed_contract(ctx):
    assert_openapi_matches(ctx.app, CONTRACTS / "openapi" / "catalogue.json")
