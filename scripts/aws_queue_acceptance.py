"""Prove real SQS retry/DLQ routing and duplicate notification suppression.

Sends two copies of one valid synthetic event and one deliberately malformed event
to the notification queue. Deletes only this runner's own DLQ message after proof.
Refuses a nonempty DLQ so existing failure evidence is never consumed.
"""

from __future__ import annotations

import importlib.util
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from aws_acceptance import Acceptance, require
from aws_backlog_acceptance import notification_count

ROOT = Path(__file__).resolve().parents[1]


def main():
    a = Acceptance("queue-reliability")
    sqs = a.session.client("sqs")
    source = sqs.get_queue_url(QueueName="booking-test-notification-events")["QueueUrl"]
    attributes = sqs.get_queue_attributes(QueueUrl=source, AttributeNames=["RedrivePolicy"])["Attributes"]
    redrive = json.loads(attributes["RedrivePolicy"])
    dlq_arn = redrive["deadLetterTargetArn"]
    dlq = sqs.get_queue_url(QueueName=dlq_arn.split(":")[-1])["QueueUrl"]
    existing = sqs.get_queue_attributes(
        QueueUrl=dlq, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"]
    )["Attributes"]
    require(all(int(v) == 0 for v in existing.values()), "Existing DLQ evidence is present; inspect it separately")
    spec = importlib.util.spec_from_file_location("backlog_events", ROOT / "tests/load/event_backlog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run = uuid.uuid4().hex[:8]
    valid = module.envelope(0, run)
    invalid = {**valid, "event_id": str(uuid.uuid4()), "producer": "acceptance-malformed-test", "data": {}}
    observed = None
    receipt = None
    try:
        copies = [sqs.send_message(QueueUrl=source, MessageBody=json.dumps(valid))["MessageId"] for _ in range(2)]
        failed_id = sqs.send_message(QueueUrl=source, MessageBody=json.dumps(invalid))["MessageId"]
        a.record(
            "queue_test_messages_sent",
            valid_event_id=valid["event_id"],
            duplicate_message_ids=copies,
            malformed_event_id=invalid["event_id"],
            malformed_message_id=failed_id,
            configured_max_receive_count=int(redrive["maxReceiveCount"]),
        )
        started = time.monotonic()
        while time.monotonic() - started < 600:
            result = sqs.receive_message(
                QueueUrl=dlq,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=10,
                VisibilityTimeout=20,
                MessageSystemAttributeNames=["ApproximateReceiveCount"],
            )
            for message in result.get("Messages", []):
                payload = json.loads(message["Body"])
                if payload.get("event_id") == invalid["event_id"]:
                    receipt = message["ReceiptHandle"]
                    observed = {
                        "observed_at": datetime.now(UTC).isoformat(),
                        "seconds": time.monotonic() - started,
                        "event_id": payload["event_id"],
                        "message_id": message["MessageId"],
                        "receive_count": int(message["Attributes"]["ApproximateReceiveCount"]),
                    }
                    break
                sqs.change_message_visibility(QueueUrl=dlq, ReceiptHandle=message["ReceiptHandle"], VisibilityTimeout=0)
            if observed:
                break
        require(observed, "Malformed notification event did not reach the DLQ")
        a.record("malformed_event_retried_then_dead_lettered", **observed)
        # Remove only the one synthetic failed message just observed; other messages are untouched.
        sqs.delete_message(QueueUrl=dlq, ReceiptHandle=receipt)
        receipt = None
        persisted = notification_count(a, a.original["notification"]["taskDefinition"], valid["data"]["customer_id"])
        passed = persisted == 1 and observed["receive_count"] > int(redrive["maxReceiveCount"])
        a.record(
            "duplicate_suppression_and_dlq",
            passed=passed,
            duplicate_copies_sent=2,
            persisted_notifications=persisted,
            failed_event_receive_count=observed["receive_count"],
        )
        a.records.update(completed=True, passed=passed)
        require(passed, "Duplicate/DLQ acceptance failed")
    except BaseException as exc:
        a.records.update(passed=False, failure=str(exc))
        raise
    finally:
        if receipt:
            sqs.change_message_visibility(QueueUrl=dlq, ReceiptHandle=receipt, VisibilityTimeout=0)
        a.save()
        print("Evidence:", a.path, flush=True)


if __name__ == "__main__":
    main()
