"""Publish/subscribe on Amazon SNS and SQS (moto locally, same code path).

Consumers record each processed event_id in the same transaction as their own changes,
so a redelivered message is skipped. A message that keeps failing is left on the queue
and SQS moves it to the dead-letter queue after maxReceiveCount attempts.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import boto3
from botocore.config import Config
from opentelemetry import propagate, trace
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import Database

log = logging.getLogger(__name__)
tracer = trace.get_tracer("platform_common.messaging")

EventHandler = Callable[[Session, dict[str, Any]], None]


class Publisher(Protocol):
    def publish(self, envelope: dict[str, Any]) -> None: ...

    def publish_batch(self, envelopes: list[dict[str, Any]]) -> set[str]:
        """Publish up to 10 events; returns the event_ids that failed."""
        ...


def _aws_client(service: str, region: str, endpoint_url: str | None):
    return boto3.client(
        service,
        region_name=region,
        endpoint_url=endpoint_url,
        config=Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=3, read_timeout=25),
    )


class SnsPublisher:
    def __init__(self, topic_arn: str, *, region: str, endpoint_url: str | None = None):
        self._topic_arn = topic_arn
        self._client = _aws_client("sns", region, endpoint_url)

    def publish(self, envelope: dict[str, Any]) -> None:
        with tracer.start_as_current_span(f"publish {envelope['event_type']}", kind=trace.SpanKind.PRODUCER):
            self._client.publish(
                TopicArn=self._topic_arn,
                Message=json.dumps(envelope),
                MessageAttributes={"event_type": {"DataType": "String", "StringValue": envelope["event_type"]}},
            )

    def publish_batch(self, envelopes: list[dict[str, Any]]) -> set[str]:
        with tracer.start_as_current_span("publish batch", kind=trace.SpanKind.PRODUCER) as span:
            span.set_attribute("messaging.batch.message_count", len(envelopes))
            response = self._client.publish_batch(
                TopicArn=self._topic_arn,
                PublishBatchRequestEntries=[
                    {
                        "Id": str(i),
                        "Message": json.dumps(e),
                        "MessageAttributes": {"event_type": {"DataType": "String", "StringValue": e["event_type"]}},
                    }
                    for i, e in enumerate(envelopes)
                ],
            )
        return {envelopes[int(f["Id"])]["event_id"] for f in response.get("Failed", [])}


class InMemoryPublisher:
    """Collects published events; used by tests and when no topic is configured."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def publish(self, envelope: dict[str, Any]) -> None:
        with self._lock:
            self.events.append(envelope)

    def publish_batch(self, envelopes: list[dict[str, Any]]) -> set[str]:
        for envelope in envelopes:
            self.publish(envelope)
        return set()

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["event_type"] == event_type]


def unwrap_sqs_body(body: str) -> dict[str, Any]:
    payload = json.loads(body)
    # Without raw message delivery SNS wraps the message in a notification document.
    if payload.get("Type") == "Notification" and "Message" in payload:
        payload = json.loads(payload["Message"])
    return payload


class EventProcessor:
    """Applies one event exactly once per consumer database."""

    def __init__(self, db: Database, handlers: dict[str, EventHandler], service_name: str):
        self._db = db
        self._handlers = handlers
        self._service_name = service_name

    def handle(self, envelope: dict[str, Any]) -> bool:
        """Returns True when the event was applied, False when skipped."""
        handler = self._handlers.get(envelope.get("event_type", ""))
        if handler is None:
            return False
        context = propagate.extract(envelope.get("trace") or {})
        with tracer.start_as_current_span(
            f"process {envelope['event_type']}",
            context=context,
            kind=trace.SpanKind.CONSUMER,
            attributes={"messaging.message.id": envelope["event_id"], "service.consumer": self._service_name},
        ):
            with self._db.session() as session:
                inserted = session.execute(
                    text(
                        "INSERT INTO processed_events (event_id, event_type) VALUES (:id, :t) "
                        "ON CONFLICT (event_id) DO NOTHING RETURNING event_id"
                    ),
                    {"id": envelope["event_id"], "t": envelope["event_type"]},
                ).first()
                if inserted is None:
                    session.rollback()
                    log.info("skipping duplicate event %s", envelope["event_id"])
                    return False
                handler(session, envelope)
                session.commit()
                # Side effects that must only happen once the change is visible (e.g. cache invalidation).
                for callback in session.info.pop("after_commit", []):
                    callback()
                return True


class SqsConsumer:
    def __init__(
        self,
        processor: EventProcessor,
        queue_url: str,
        *,
        region: str,
        endpoint_url: str | None = None,
        concurrency: int = 1,
        wait_seconds: int = 20,
    ):
        self._processor = processor
        self._queue_url = queue_url
        self._client = _aws_client("sqs", region, endpoint_url)
        self._concurrency = max(1, concurrency)
        self._wait_seconds = wait_seconds
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.processed = 0
        self.failed = 0

    def poll_once(self, wait_seconds: int | None = None) -> int:
        wait_seconds = self._wait_seconds if wait_seconds is None else wait_seconds
        response = self._client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=wait_seconds,
            VisibilityTimeout=30,
        )
        messages = response.get("Messages", [])
        done = []
        for message in messages:
            try:
                envelope = unwrap_sqs_body(message["Body"])
                self._processor.handle(envelope)
                done.append({"Id": message["MessageId"], "ReceiptHandle": message["ReceiptHandle"]})
                self.processed += 1
            except Exception:  # noqa: BLE001 - leave the message for retry / DLQ
                self.failed += 1
                log.exception("failed to process message %s", message.get("MessageId"))
        if done:
            # Failed messages are not deleted: they reappear after the visibility timeout.
            self._client.delete_message_batch(QueueUrl=self._queue_url, Entries=done)
        return len(messages)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self.poll_once() == 0 and self._wait_seconds < 5:
                    self._stop.wait(0.5)  # short polling: avoid a busy loop on an empty queue
            except Exception:  # noqa: BLE001
                log.warning("queue poll failed; retrying", exc_info=True)
                time.sleep(2)

    def start(self) -> None:
        for i in range(self._concurrency):
            thread = threading.Thread(target=self._run, name=f"sqs-consumer-{i}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=15)
