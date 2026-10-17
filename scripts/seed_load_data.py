"""Seed the scalability test dataset through the public API.

Default: 100 merchants x 10 resources = 1,000 resources, 2 days x 10 hours = 20 slots each,
so 20,000 future slots.

  python scripts/seed_load_data.py
  python scripts/seed_load_data.py --merchants 10 --resources 5     # smaller run
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_client import Api, Config, login  # noqa: E402

RESOURCE_TYPES = ["badminton_court", "tennis_court", "squash_court", "futsal_pitch", "basketball_court"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--merchants", type=int, default=100)
    parser.add_argument("--resources", type=int, default=10, help="per merchant")
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--start-hour", type=int, default=8)
    parser.add_argument("--end-hour", type=int, default=18)
    parser.add_argument("--starts-in-days", type=int, default=1)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--prefix", default="load")
    args = parser.parse_args()

    cfg = Config(api_key=os.environ.get("PLATFORM_API_KEY", "local-loadtest-key"))
    token = login(cfg, os.environ.get("PLATFORM_ADMIN_USER", "admin"), os.environ.get("PLATFORM_ADMIN_PASSWORD", "Passw0rd!"))
    first = date.today() + timedelta(days=args.starts_in_days)
    last = first + timedelta(days=args.days - 1)
    existing = {m["slug"]: m for m in Api(cfg, token).call("GET", "/v1/merchants").json()}
    started = time.perf_counter()

    def seed_merchant(i: int) -> int:
        api = Api(cfg, token)
        slug = f"{args.prefix}-merchant-{i:03d}"
        merchant = existing.get(slug) or api.call(
            "POST",
            "/v1/merchants",
            json={"name": f"Load Test Venue {i:03d}", "slug": slug, "contact_email": f"{slug}@load.test"},
        ).json()
        have = {r["name"]: r for r in api.call("GET", "/v1/resources", params={"merchant_id": merchant["merchant_id"]}).json()}
        created = 0
        for r in range(args.resources):
            name = f"Court {r + 1:02d}"
            resource = have.get(name) or api.call(
                "POST",
                "/v1/resources",
                json={"merchant_id": merchant["merchant_id"], "name": name, "resource_type": RESOURCE_TYPES[r % len(RESOURCE_TYPES)]},
            ).json()
            created += api.call(
                "POST",
                f"/v1/resources/{resource['resource_id']}/slots",
                json={
                    "from_date": first.isoformat(),
                    "to_date": last.isoformat(),
                    "start_hour": args.start_hour,
                    "end_hour": args.end_hour,
                    "skip_existing": True,
                },
            ).json()["created"]
        return created

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        total = 0
        for i, count in enumerate(pool.map(seed_merchant, range(1, args.merchants + 1)), start=1):
            total += count
            if i % 10 == 0:
                print(f"  {i} merchants seeded, {total} slots so far ({time.perf_counter() - started:.0f}s)")
    print(f"seeded {args.merchants} merchants, {args.merchants * args.resources} resources, {total} new slots "
          f"for {first}..{last} in {time.perf_counter() - started:.0f}s")


if __name__ == "__main__":
    main()
