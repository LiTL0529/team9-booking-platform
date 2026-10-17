from conftest import CONTRACTS

from platform_common.testing import assert_valid_event


def onboard(ctx, admin, slug="city-courts"):
    response = ctx.client.post(
        "/v1/merchants", json={"name": "City Courts", "slug": slug, "contact_email": "ops@city.test"}, headers=admin
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_platform_admin_onboards_merchant_and_event_is_published(ctx, admin):
    merchant = onboard(ctx, admin)
    assert ctx.app.state.relay.drain_all() == 1
    [event] = ctx.publisher.of_type("MerchantOnboarded")
    assert event["data"]["merchant_id"] == merchant["merchant_id"]
    assert_valid_event(event, CONTRACTS)


def test_duplicate_slug_is_rejected(ctx, admin):
    onboard(ctx, admin)
    response = ctx.client.post(
        "/v1/merchants", json={"name": "Other", "slug": "city-courts", "contact_email": "a@b.test"}, headers=admin
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slug_taken"


def test_customer_cannot_onboard_and_anonymous_is_unauthorised(ctx, keys):
    body = {"name": "X", "slug": "x-x", "contact_email": "a@b.test"}
    assert ctx.client.post("/v1/merchants", json=body, headers=keys.headers("alice", ["customer"])).status_code == 403
    assert ctx.client.post("/v1/merchants", json=body).status_code == 401


def test_assign_member_writes_role_to_identity_provider(ctx, admin):
    merchant = onboard(ctx, admin)
    response = ctx.client.post(
        f"/v1/merchants/{merchant['merchant_id']}/members",
        json={"username": "owner1", "role": "merchant_admin"},
        headers=admin,
    )
    assert response.status_code == 201
    assert response.json()["sync_status"] == "SYNCED"
    assert ctx.identity.assigned == [("owner1", merchant["merchant_id"], "merchant_admin")]


def test_unknown_user_is_not_assigned(ctx, admin):
    merchant = onboard(ctx, admin)
    ctx.identity.missing.add("ghost")
    url = f"/v1/merchants/{merchant['merchant_id']}/members"
    assert ctx.client.post(url, json={"username": "ghost"}, headers=admin).status_code == 404
    assert ctx.client.get(url, headers=admin).json() == []


def test_identity_provider_outage_leaves_membership_pending_until_resync(ctx, admin):
    merchant = onboard(ctx, admin)
    ctx.identity.fail = True
    url = f"/v1/merchants/{merchant['merchant_id']}/members"
    assert ctx.client.post(url, json={"username": "staff1"}, headers=admin).json()["sync_status"] == "PENDING"
    ctx.identity.fail = False
    response = ctx.client.post(f"{url}/staff1/sync", headers=admin)
    assert response.status_code == 200
    assert response.json()["sync_status"] == "SYNCED"


def test_merchant_admin_cannot_manage_another_merchant(ctx, admin, keys):
    first = onboard(ctx, admin, "first")
    second = onboard(ctx, admin, "second")
    owner = keys.headers("owner1", ["merchant_admin"], merchant_id=first["merchant_id"])
    assert ctx.client.get(f"/v1/merchants/{first['merchant_id']}", headers=owner).status_code == 200
    assert ctx.client.get(f"/v1/merchants/{second['merchant_id']}", headers=owner).status_code == 403
    response = ctx.client.post(
        f"/v1/merchants/{second['merchant_id']}/members", json={"username": "x"}, headers=owner
    )
    assert response.status_code == 403
    assert ctx.client.get("/v1/merchants/me", headers=owner).json()["slug"] == "first"


def test_user_cannot_belong_to_two_merchants(ctx, admin):
    first = onboard(ctx, admin, "first")
    second = onboard(ctx, admin, "second")
    ctx.client.post(f"/v1/merchants/{first['merchant_id']}/members", json={"username": "u1"}, headers=admin)
    response = ctx.client.post(f"/v1/merchants/{second['merchant_id']}/members", json={"username": "u1"}, headers=admin)
    assert response.status_code == 409
