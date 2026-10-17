"""Writes merchant roles to the identity provider so they travel as token claims.

Services then authorise merchant users from the token alone, without calling this
service on every request.
"""

from __future__ import annotations

from typing import Protocol

import boto3

from platform_common.resilience import ResilientClient


class UserNotFound(Exception):
    pass


class IdentityDirectory(Protocol):
    def assign_merchant_role(self, username: str, merchant_id: str, role: str) -> None: ...


class DevAuthDirectory:
    def __init__(self, base_url: str, admin_secret: str):
        self._client = ResilientClient(
            base_url, name="dev-auth", timeout=2.0, headers={"X-Admin-Secret": admin_secret}
        )

    def assign_merchant_role(self, username: str, merchant_id: str, role: str) -> None:
        response = self._client.post(
            f"/admin/users/{username}/merchant", json={"merchant_id": merchant_id, "role": role}
        )
        if response.status_code == 404:
            raise UserNotFound(username)
        response.raise_for_status()


class CognitoDirectory:
    ROLE_GROUPS = ("merchant_admin", "merchant_staff")

    def __init__(self, user_pool_id: str, region: str):
        self._pool = user_pool_id
        self._client = boto3.client("cognito-idp", region_name=region)

    def assign_merchant_role(self, username: str, merchant_id: str, role: str) -> None:
        try:
            self._client.admin_update_user_attributes(
                UserPoolId=self._pool,
                Username=username,
                UserAttributes=[{"Name": "custom:merchant_id", "Value": merchant_id}],
            )
        except self._client.exceptions.UserNotFoundException as exc:
            raise UserNotFound(username) from exc
        for group in self.ROLE_GROUPS:
            if group != role:
                self._client.admin_remove_user_from_group(UserPoolId=self._pool, Username=username, GroupName=group)
        self._client.admin_add_user_to_group(UserPoolId=self._pool, Username=username, GroupName=role)


class NullDirectory:
    """Used in tests."""

    def __init__(self) -> None:
        self.assigned: list[tuple[str, str, str]] = []
        self.missing: set[str] = set()
        self.fail = False

    def assign_merchant_role(self, username: str, merchant_id: str, role: str) -> None:
        if username in self.missing:
            raise UserNotFound(username)
        if self.fail:
            raise RuntimeError("identity provider unavailable")
        self.assigned.append((username, merchant_id, role))


def build_directory(settings) -> IdentityDirectory:
    if settings.identity_provider == "cognito":
        return CognitoDirectory(settings.cognito_user_pool_id, settings.aws_region)
    return DevAuthDirectory(settings.dev_auth_url, settings.dev_auth_admin_secret)
