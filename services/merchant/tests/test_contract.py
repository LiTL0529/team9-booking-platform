from conftest import CONTRACTS

from platform_common.testing import assert_openapi_matches


def test_openapi_matches_committed_contract(ctx):
    assert_openapi_matches(ctx.app, CONTRACTS / "openapi" / "merchant.json")
