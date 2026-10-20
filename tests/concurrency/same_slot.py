"""Booking correctness under concurrency, against a running deployment.

Sends N concurrent booking requests for the same slot through the gateway (spread over
several Booking Service tasks) and checks that exactly one succeeds.

  python tests/concurrency/same_slot.py --requests 100
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from platform_client import Config, login  # noqa: E402


def assess_results(results, requests: int, min_tasks: int):
    statuses = collections.Counter(status for status, _ in results)
    tasks = collections.Counter(host for _, host in results)
    known_tasks = {host for host in tasks if host not in {'?', 'network-error'}}
    passed = (statuses.get(201) == 1 and statuses.get(409, 0) == requests - 1
              and len(results) == requests and len(known_tasks) >= min_tasks)
    return {'passed': passed, 'status_counts': dict(statuses), 'served_by': dict(tasks),
            'distinct_tasks': len(known_tasks), 'required_tasks': min_tasks, 'requests': requests}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--date", default=(date.today() + timedelta(days=1)).isoformat())
    parser.add_argument('--min-tasks', type=int, default=1)
    parser.add_argument('--output', type=Path)
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
    assessment = assess_results(results, args.requests, args.min_tasks)
    assessment.update(at=datetime.now(UTC).isoformat(), slot_id=slot_id)
    print(f"status codes: {assessment['status_counts']}")
    print(f"served by {assessment['distinct_tasks']} booking task(s): {assessment['served_by']}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(assessment, indent=2), encoding='utf-8')
    if assessment['passed']:
        print("PASS: exactly one booking succeeded, every other request got 409 Conflict")
    else:
        sys.exit("FAIL: require exactly one 201, all other requests 409, and the requested task distribution")


if __name__ == "__main__":
    asyncio.run(main())
