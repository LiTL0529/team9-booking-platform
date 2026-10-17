"""Onboard a merchant from a configuration file, without changing any service code.

  python scripts/onboard_merchant.py merchants/eastside-sports.yaml

Repeatable: running it again finds the existing merchant and resources and only publishes
slots that are still missing. The script prints how long each step took, which is the
evidence for the "second merchant without code change" demonstration.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_client import Api, Config, login  # noqa: E402


def step(label: str, started: float) -> None:
    print(f"  [{time.perf_counter() - started:6.2f}s] {label}")


def onboard(config: dict, cfg: Config, admin_user: str, admin_password: str) -> None:
    started = time.perf_counter()
    admin = Api(cfg, login(cfg, admin_user, admin_password))
    spec = config["merchant"]

    existing = {m["slug"]: m for m in admin.call("GET", "/v1/merchants").json()}
    if spec["slug"] in existing:
        merchant = existing[spec["slug"]]
        step(f"merchant '{spec['slug']}' already onboarded", started)
    else:
        merchant = admin.call("POST", "/v1/merchants", json=spec).json()
        step(f"onboarded merchant {merchant['name']} ({merchant['merchant_id']})", started)
    merchant_id = merchant["merchant_id"]

    for member in config.get("members", []):
        result = admin.call("POST", f"/v1/merchants/{merchant_id}/members", json=member).json()
        step(f"assigned {member['username']} as {member['role']} (sync {result['sync_status']})", started)

    resources = {r["name"]: r for r in admin.call("GET", "/v1/resources", params={"merchant_id": merchant_id}).json()}
    schedule = config.get("schedule", {})
    first = date.today() + timedelta(days=schedule.get("starts_in_days", 1))
    last = first + timedelta(days=schedule.get("days", 7) - 1)
    total = 0
    for item in config.get("resources", []):
        resource = resources.get(item["name"]) or admin.call(
            "POST", "/v1/resources", json={"merchant_id": merchant_id, **item}
        ).json()
        published = admin.call(
            "POST",
            f"/v1/resources/{resource['resource_id']}/slots",
            json={
                "from_date": first.isoformat(),
                "to_date": last.isoformat(),
                "start_hour": schedule.get("start_hour", 9),
                "end_hour": schedule.get("end_hour", 21),
                "skip_existing": True,
            },
        ).json()
        total += published["created"]
        step(f"{item['name']}: {published['created']} slots published", started)
    step(f"done: {len(config.get('resources', []))} resources, {total} new slots, no code changes", started)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", type=Path)
    parser.add_argument("--admin-user", default=os.environ.get("PLATFORM_ADMIN_USER", "admin"))
    parser.add_argument("--admin-password", default=os.environ.get("PLATFORM_ADMIN_PASSWORD", "Passw0rd!"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    print(f"onboarding from {args.config}")
    onboard(config, Config(), args.admin_user, args.admin_password)


if __name__ == "__main__":
    main()
