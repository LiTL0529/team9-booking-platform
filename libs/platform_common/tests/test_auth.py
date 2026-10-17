import json

import pytest

from platform_common.auth import Principal
from platform_common.errors import Unauthorized
from platform_common.messaging import unwrap_sqs_body
from platform_common.testing import TestKeys


@pytest.fixture(scope="module")
def keys():
    return TestKeys()


def test_valid_token_produces_principal(keys):
    token = keys.token("owner", ["merchant_admin"], merchant_id="m-1")
    principal = keys.verifier.verify(token)
    assert principal.username == "owner"
    assert principal.is_member_of("m-1")
    assert not principal.is_member_of("m-2")
    assert principal.can_manage_merchant("m-1")


def test_expired_token_is_rejected(keys):
    with pytest.raises(Unauthorized):
        keys.verifier.verify(keys.token("alice", ["customer"], expires_in=-10))


def test_token_from_another_key_is_rejected(keys):
    other = TestKeys()
    with pytest.raises(Unauthorized):
        keys.verifier.verify(other.token("mallory", ["platform_admin"]))


def test_customer_with_merchant_claim_is_not_a_member():
    principal = Principal(sub="s", username="u", groups=frozenset({"customer"}), merchant_id="m-1")
    assert not principal.is_member_of("m-1")


def test_platform_admin_can_manage_any_merchant():
    principal = Principal(sub="s", username="admin", groups=frozenset({"platform_admin"}))
    assert principal.can_manage_merchant("anything")


def test_unwrap_handles_raw_and_sns_wrapped_messages():
    envelope = {"event_id": "1", "event_type": "X"}
    assert unwrap_sqs_body(json.dumps(envelope)) == envelope
    wrapped = {"Type": "Notification", "Message": json.dumps(envelope)}
    assert unwrap_sqs_body(json.dumps(wrapped)) == envelope
