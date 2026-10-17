"""Creates the local event bus on moto: the same topics, queues, DLQs and subscriptions
that infra/terraform creates in AWS. Idempotent, so it is safe to run on every start.
"""

from __future__ import annotations

import json
import os
import sys
import time

import boto3

ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://127.0.0.1:5000")
REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
MAX_RECEIVE_COUNT = int(os.environ.get("MAX_RECEIVE_COUNT", "5"))

TOPICS = ["merchant-events", "catalogue-events", "booking-events"]
# queue -> topics it subscribes to
QUEUES = {
    "availability-events": ["merchant-events", "catalogue-events", "booking-events"],
    "booking-slot-events": ["catalogue-events"],
    "notification-events": ["booking-events"],
}


def main() -> None:
    sns = boto3.client("sns", endpoint_url=ENDPOINT, region_name=REGION)
    sqs = boto3.client("sqs", endpoint_url=ENDPOINT, region_name=REGION)
    for _attempt in range(30):
        try:
            sns.list_topics()
            break
        except Exception:  # noqa: BLE001 - wait for moto to come up
            time.sleep(1)
    else:
        sys.exit("moto is not reachable at " + ENDPOINT)

    topic_arns = {name: sns.create_topic(Name=name)["TopicArn"] for name in TOPICS}
    for queue, topics in QUEUES.items():
        dlq_url = sqs.create_queue(QueueName=f"{queue}-dlq")["QueueUrl"]
        dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        url = sqs.create_queue(
            QueueName=queue,
            Attributes={
                "VisibilityTimeout": "30",
                "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": MAX_RECEIVE_COUNT}),
            },
        )["QueueUrl"]
        arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        existing = {
            s["TopicArn"]
            for page in sns.get_paginator("list_subscriptions").paginate()
            for s in page["Subscriptions"]
            if s["Endpoint"] == arn
        }
        for topic in topics:
            if topic_arns[topic] not in existing:
                sns.subscribe(
                    TopicArn=topic_arns[topic],
                    Protocol="sqs",
                    Endpoint=arn,
                    Attributes={"RawMessageDelivery": "true"},
                )
        print(f"queue {queue}: {url} <- {', '.join(topics)}")
    for name, arn in topic_arns.items():
        print(f"topic {name}: {arn}")


if __name__ == "__main__":
    main()
