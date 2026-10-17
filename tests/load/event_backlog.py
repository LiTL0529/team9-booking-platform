"""Event backlog test: publish 5,000 booking events at once and time how long the
Notification Service takes to drain its queue (it scales out on queue depth in AWS).

  python tests/load/event_backlog.py --events 5000
  # AWS: python tests/load/event_backlog.py --aws with
  #      BOOKING_TOPIC_ARN=arn:aws:sns:...:booking-events NOTIFICATION_QUEUE_URL=https://sqs.../notification-events
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import boto3

ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://127.0.0.1:5000")
REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
TOPIC = os.environ.get("BOOKING_TOPIC_ARN", f"arn:aws:sns:{REGION}:123456789012:booking-events")
QUEUE = os.environ.get("NOTIFICATION_QUEUE_URL", f"{ENDPOINT}/123456789012/notification-events")


def envelope(i: int, run: str) -> dict:
    start = datetime.now(UTC) + timedelta(days=3, hours=i % 12)
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "BookingConfirmed",
        "event_version": 1,
        "occurred_at": datetime.now(UTC).isoformat(),
        "producer": "backlog-test",
        "trace": {},
        "data": {
            "booking_id": str(uuid.uuid4()),
            "reference": f"BK-LOAD{i:04d}"[:11],
            "slot_id": str(uuid.uuid4()),
            "slot_version": 1,
            "customer_id": f"backlog-{run}",
            "customer_username": "backlog-test",
            "merchant_id": str(uuid.uuid4()),
            "resource_id": str(uuid.uuid4()),
            "resource_name": "Backlog Court",
            "resource_type": "badminton_court",
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(hours=1)).isoformat(),
            "local_date": start.date().isoformat(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=5000)
    parser.add_argument("--aws", action="store_true", help="use real AWS instead of local moto")
    args = parser.parse_args()
    endpoint = None if args.aws else ENDPOINT
    sns = boto3.client("sns", endpoint_url=endpoint, region_name=REGION)
    sqs = boto3.client("sqs", endpoint_url=endpoint, region_name=REGION)
    run = uuid.uuid4().hex[:8]
    batches = [
        [{"Id": str(j), "Message": json.dumps(envelope(i + j, run)),
          "MessageAttributes": {"event_type": {"DataType": "String", "StringValue": "BookingConfirmed"}}}
         for j in range(min(10, args.events - i))]
        for i in range(0, args.events, 10)
    ]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda b: sns.publish_batch(TopicArn=TOPIC, PublishBatchRequestEntries=b), batches))
    print(f"published {args.events} events in {time.perf_counter() - started:.1f}s; waiting for the queue to drain")
    while True:
        attrs = sqs.get_queue_attributes(
            QueueUrl=QUEUE, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"]
        )["Attributes"]
        visible = int(attrs["ApproximateNumberOfMessages"])
        in_flight = int(attrs["ApproximateNumberOfMessagesNotVisible"])
        print(f"  t={time.perf_counter() - started:6.1f}s  queued={visible:5d}  in-flight={in_flight:4d}")
        if visible == 0 and in_flight == 0:
            break
        time.sleep(5)
    print(f"backlog of {args.events} events cleared in {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
