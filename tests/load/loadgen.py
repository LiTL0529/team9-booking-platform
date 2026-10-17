"""Stepped open-model load generator (Python fallback when k6 is not installed).

Same traffic mix as tests/load/k6-search-and-book.js: 80% availability searches and 20%
booking operations (search then book). Each step holds a fixed arrival rate and reports
throughput, P95 latency per operation, expected conflicts and unexpected errors.

  python tests/load/loadgen.py --steps 25,50,100 --step-seconds 30
  python tests/load/loadgen.py --steps 25,50,100,150,200 --step-seconds 300 --hold 600   # proposal profile
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics
import sys
import time
import uuid
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from platform_client import Config, login  # noqa: E402


class Stats:
    def __init__(self):
        self.latency: dict[str, list[float]] = defaultdict(list)
        self.status: dict[str, int] = defaultdict(int)
        self.conflicts = 0
        self.unexpected = 0
        self.done = 0

    def record(self, op: str, started: float, status: int) -> None:
        self.latency[op].append((time.perf_counter() - started) * 1000)
        self.status[f"{op}:{status}"] += 1
        self.done += 1
        if status == 409:
            self.conflicts += 1
        if status >= 500 or status == 0:
            self.unexpected += 1

    @staticmethod
    def p95(values: list[float]) -> float:
        return statistics.quantiles(values, n=20)[18] if len(values) >= 20 else max(values, default=0)


async def run(args) -> None:
    cfg = Config(api_key=os.environ.get("PLATFORM_API_KEY", "local-loadtest-key"))
    token = login(cfg, os.environ.get("LOAD_USER", "loadtester"), os.environ.get("LOAD_PASSWORD", "Passw0rd!"))
    days = [(date.today() + timedelta(days=d)).isoformat() for d in range(1, args.days + 1)]
    async with httpx.AsyncClient(
        base_url=cfg.gateway, headers={"x-api-key": cfg.api_key}, timeout=10, limits=httpx.Limits(max_connections=400)
    ) as client:
        merchants = [m["merchant_id"] for m in (await client.get("/v1/availability/merchants")).json()]
        auth = {"Authorization": f"Bearer {token}"}

        async def search(stats: Stats) -> list[dict]:
            params = {"date": random.choice(days)}  # noqa: S311
            if merchants and random.random() < 0.7:  # noqa: S311
                params["merchant_id"] = random.choice(merchants)  # noqa: S311
            started = time.perf_counter()
            try:
                response = await client.get("/v1/availability/slots", params=params)
                stats.record("search", started, response.status_code)
                return response.json()["slots"] if response.status_code == 200 else []
            except httpx.HTTPError:
                stats.record("search", started, 0)
                return []

        async def book(stats: Stats) -> None:
            slots = await search(stats)
            if not slots:
                return
            started = time.perf_counter()
            try:
                response = await client.post(
                    "/v1/bookings",
                    json={"slot_id": random.choice(slots)["slot_id"]},  # noqa: S311
                    headers={**auth, "Idempotency-Key": str(uuid.uuid4())},
                )
                stats.record("book", started, response.status_code)
            except httpx.HTTPError:
                stats.record("book", started, 0)

        steps = [int(s) for s in args.steps.split(",")]
        plan = [(rate, args.step_seconds) for rate in steps] + ([(steps[-1], args.hold)] if args.hold else [])
        print(f"{'rate':>5} {'secs':>5} {'achieved':>9} {'search p95':>11} {'book p95':>9} {'conflicts':>9} {'5xx/err':>8}")
        for rate, seconds in plan:
            stats, tasks = Stats(), set()
            started = time.perf_counter()
            for i in range(rate * seconds):
                target = started + i / rate
                delay = target - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
                task = asyncio.create_task(book(stats) if random.random() < 0.2 else search(stats))  # noqa: S311
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            await asyncio.gather(*tasks)
            elapsed = time.perf_counter() - started
            print(
                f"{rate:>5} {seconds:>5} {stats.done / elapsed:>8.1f}/s "
                f"{stats.p95(stats.latency['search']):>9.0f}ms {stats.p95(stats.latency['book']):>7.0f}ms "
                f"{stats.conflicts:>9} {stats.unexpected:>8}"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", default="25,50,100")
    parser.add_argument("--step-seconds", type=int, default=30)
    parser.add_argument("--hold", type=int, default=0, help="seconds to hold the last rate")
    parser.add_argument("--days", type=int, default=2)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
