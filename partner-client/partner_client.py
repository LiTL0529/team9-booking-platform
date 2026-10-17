"""Partner integration client.

A separate application with its own API key and usage plan that reuses the platform's
published availability and booking APIs. It contains no booking rules, no storage and no
notification logic: all of that comes from the platform.

  python partner-client/partner_client.py search --date 2026-10-25 --type badminton_court
  python partner-client/partner_client.py book --date 2026-10-25 --type badminton_court
  python partner-client/partner_client.py bookings
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

GATEWAY = os.environ.get("PARTNER_GATEWAY", "http://127.0.0.1:8080")
API_KEY = os.environ.get("PARTNER_API_KEY", "local-partner-key")
USERNAME = os.environ.get("PARTNER_USERNAME", "partner")
PASSWORD = os.environ.get("PARTNER_PASSWORD", "Passw0rd!")
COGNITO_CLIENT_ID = os.environ.get("PARTNER_COGNITO_CLIENT_ID")
ZONE = ZoneInfo(os.environ.get("PARTNER_TIMEZONE", "Asia/Singapore"))


def local(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(ZONE).strftime("%a %d %b %H:%M")


def token() -> str:
    if COGNITO_CLIENT_ID:
        import boto3

        auth = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "ap-southeast-1")).initiate_auth(
            ClientId=COGNITO_CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": USERNAME, "PASSWORD": PASSWORD},
        )
        return auth["AuthenticationResult"]["IdToken"]
    response = httpx.post(f"{GATEWAY}/auth/login", json={"username": USERNAME, "password": PASSWORD}, timeout=10)
    response.raise_for_status()
    return response.json()["id_token"]


def client(authenticated: bool = False) -> httpx.Client:
    headers = {"x-api-key": API_KEY, "User-Agent": "partner-client/1.0"}
    if authenticated:
        headers["Authorization"] = f"Bearer {token()}"
    return httpx.Client(base_url=GATEWAY, headers=headers, timeout=15)


def search(day: str, resource_type: str | None) -> list[dict]:
    params = {"date": day}
    if resource_type:
        params["resource_type"] = resource_type
    response = client().get("/v1/availability/slots", params=params)
    response.raise_for_status()
    return response.json()["slots"]


def cmd_search(args) -> None:
    slots = search(args.date, args.type)
    print(f"{len(slots)} available slots on {args.date}")
    for s in slots[: args.limit]:
        print(f"  {local(s['start_time'])}  {s['merchant_name']:<24} {s['resource_name']:<20} {s['slot_id']}")


def cmd_book(args) -> None:
    slots = search(args.date, args.type)
    if not slots:
        sys.exit("no available slots")
    api = client(authenticated=True)
    key = str(uuid.uuid4())
    for slot in slots[:5]:  # the read model may lag; try the next slot on a conflict
        response = api.post("/v1/bookings", json={"slot_id": slot["slot_id"]}, headers={"Idempotency-Key": key})
        if response.status_code == 409:
            print(f"  slot {slot['slot_id']} was just taken, trying the next one")
            key = str(uuid.uuid4())
            continue
        response.raise_for_status()
        booking = response.json()
        print(f"booked {booking['reference']}: {booking['resource_name']} at {local(booking['start_time'])}")
        return
    sys.exit("could not book any of the first five slots")


def cmd_bookings(args) -> None:
    for b in client(authenticated=True).get("/v1/bookings").raise_for_status().json():
        print(f"  {b['reference']}  {b['status']:<10} {b['resource_name']:<20} {local(b['start_time'])}")


def main() -> None:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    parser = argparse.ArgumentParser(description="Partner integration client")
    sub = parser.add_subparsers(required=True)
    for name, fn in (("search", cmd_search), ("book", cmd_book)):
        p = sub.add_parser(name)
        p.add_argument("--date", default=tomorrow)
        p.add_argument("--type", default=None)
        p.add_argument("--limit", type=int, default=20)
        p.set_defaults(fn=fn)
    sub.add_parser("bookings").set_defaults(fn=cmd_bookings)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
