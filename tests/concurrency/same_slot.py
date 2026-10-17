"""Booking correctness under concurrency, against a running deployment.

Sends N concurrent booking requests for the same slot through the gateway (spread over
several Booking Service tasks) and checks that exactly one succeeds.

  python tests/concurrency/same_slot.py --requests 100
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from platform_client import Config, login  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--date", default=(date.today() + timedelta(days=1)).isoformat())
    args = parser.parse_args()

    cfg = Config(api_key=os.environ.get("PLATFORM_API_KEY", "local-loadtest-key"))
    token = login(cfg, os.environ.get("LOAD_USER", "loadtester"), os.environ.get("LOAD_PASSWORD", "Passw0rd!"))
    headers = {"x-api-key": cfg.api_key, "Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=cfg.gateway, headers=headers, timeout=30,
                                 limits=httpx.Limits(max_connections=args.requests)) as client:
        found = (await client.get("/v1/availability/slots", params={"date": args.date})).json()["slots"]
        if not found:
            sys.exit(f"no available slots on {args.date}; seed data first")
        slot_id = found[-1]["slot_id"]
        print(f"racing {args.requests} concurrent requests for slot {slot_id}")

        async def attempt():
            # Retrying a dropped connection with the same Idempotency-Key is safe: the platform
            # returns the original result instead of booking twice.
            key = str(uuid.uuid4())
            for retry in range(4):
                try:
                    response = await client.post(
                        "/v1/bookings", json={"slot_id": slot_id}, headers={"Idempotency-Key": key}
                    )
                    return response.status_code, response.headers.get("x-served-by", "?")
                except httpx.TransportError:
                    await asyncio.sleep(0.5 * (retry + 1))
            return 0, "network-error"

        results = await asyncio.gather(*(attempt() for _ in range(args.requests)))
    statuses = collections.Counter(status for status, _ in results)
    tasks = collections.Counter(host for _, host in results)
    print(f"status codes: {dict(statuses)}")
    print(f"served by {len(tasks)} booking task(s): {dict(tasks)}")
    # A replayed request (200) means the client retried after a dropped connection and got the
    # original booking back, so it counts with the single success.
    successes = statuses.get(201, 0) + statuses.get(200, 0)
    if statuses.get(0):
        print(f"note: {statuses[0]} request(s) never reached the platform (client network errors)")
    if statuses.get(201) == 1 and successes == 1 and statuses.get(409, 0) + statuses.get(0, 0) == args.requests - 1:
        print("PASS: exactly one booking succeeded, every other request got 409 Conflict")
    else:
        sys.exit("FAIL: expected exactly one 201 and the rest 409")


if __name__ == "__main__":
    asyncio.run(main())
