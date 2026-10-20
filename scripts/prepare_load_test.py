"""Prepare distinct free slots for an 80/20 HTTP workload, using GET requests only."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def get_json(gateway: str, api_key: str, params: dict) -> dict:
    request = Request(f"{gateway.rstrip('/')}/v1/availability/slots?{urlencode(params)}",
                      headers={"x-api-key": api_key})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def prepare(gateway: str, api_key: str, phases: list[dict], days: int, start_day: int) -> tuple[dict, list[str]]:
    if days < 1 or start_day < 1:
        raise ValueError("days and start-day must be positive; use future dates")
    if not phases or any(p["rate"] <= 0 or p["rate"] % 5 or p["seconds"] <= 0 for p in phases):
        raise ValueError("each phase needs a positive rate divisible by 5 and a positive duration")
    slot_ids, seen, dates, merchants_by_date = [], set(), [], {}
    for offset in range(start_day, start_day + days):
        day = (date.today() + timedelta(days=offset)).isoformat()
        dates.append(day)
        merchants, page_offset = set(), 0
        while True:
            page = get_json(gateway, api_key, {"date": day, "limit": 1000, "offset": page_offset})
            rows = page["slots"]
            for row in rows:
                if row["slot_id"] not in seen:
                    seen.add(row["slot_id"])
                    slot_ids.append(row["slot_id"])
                merchants.add(row["merchant_id"])
            if not page.get("has_more", False):
                break
            if not rows:
                raise ValueError("search reported another page but returned no slots")
            page_offset += len(rows)
        merchants_by_date[day] = sorted(merchants)
    required, start_seconds, compiled = 0, 0, []
    for phase in phases:
        bookings = phase["rate"] // 5 * phase["seconds"]
        compiled.append({**phase, "start_seconds": start_seconds, "booking_offset": required,
                         "expected_searches": phase["rate"] * 4 // 5 * phase["seconds"],
                         "expected_bookings": bookings})
        required += bookings
        start_seconds += phase["seconds"]
    if len(slot_ids) < required:
        raise ValueError(
            f"insufficient free inventory: {len(slot_ids)} available, {required} distinct slots required. "
            "Seed the dedicated dates or choose other dates; no load test has started."
        )
    return {
        "schema_version": 2, "run_id": uuid.uuid4().hex,
        "prepared_at": datetime.now(UTC).isoformat(), "gateway": gateway.rstrip('/'),
        "dates": dates, "merchants_by_date": merchants_by_date, "phases": compiled,
        "duration_seconds": start_seconds, "required_booking_slots": required,
        "available_booking_slots": len(slot_ids), "search_share": 0.8, "booking_share": 0.2,
        "inventory_strategy": "one distinct preselected slot per booking iteration; no measured lookup",
    }, slot_ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["full", "short"], default="short")
    parser.add_argument("--days", type=int)
    parser.add_argument("--start-day", type=int, default=1)
    parser.add_argument("--profiles-file", type=Path, default=Path(__file__).resolve().parents[1] / "tests/load/profiles.json")
    parser.add_argument("--manifest", type=Path, default=Path(".local/load-manifest.json"))
    parser.add_argument("--slot-file", type=Path, default=Path(".local/load-slots.json"))
    args = parser.parse_args()
    gateway = os.environ.get("GATEWAY") or os.environ["PLATFORM_GATEWAY"]
    api_key = os.environ.get("API_KEY") or os.environ["LOADTEST_API_KEY"]
    phases = json.loads(args.profiles_file.read_text(encoding="utf-8"))[args.profile]
    manifest, slots = prepare(gateway, api_key, phases, args.days or (6 if args.profile == "full" else 2), args.start_day)
    manifest["profile"] = args.profile
    for p in (args.manifest, args.slot_file):
        p.parent.mkdir(parents=True, exist_ok=True)
    args.slot_file.write_text(json.dumps(slots), encoding="utf-8")
    args.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Prepared {len(slots)} free slots; {manifest['required_booking_slots']} required; "
          f"{manifest['duration_seconds']}s measured workload, 80% search / 20% booking HTTP requests.")


if __name__ == "__main__":
    main()
