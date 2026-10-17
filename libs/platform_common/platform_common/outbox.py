"""Transactional outbox.

Domain changes and the events describing them are written in one local transaction.
A relay thread publishes committed events afterwards, so an event is never lost when the
bus is down and never sent for a change that was rolled back.
"""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .db import Database
from .events import new_envelope
from .messaging import Publisher

log = logging.getLogger(__name__)


class _OutboxBase(DeclarativeBase):
    pass


class OutboxEvent(_OutboxBase):
    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


def add_to_outbox(session: Session, event_type: str, data: dict[str, Any], producer: str) -> dict[str, Any]:
    """Stage an event in the caller's transaction. It is published only if the caller commits."""
    envelope = new_envelope(event_type, data, producer)
    session.add(
        OutboxEvent(
            id=uuid.UUID(envelope["event_id"]),
            event_type=event_type,
            payload=envelope,
            created_at=datetime.now(UTC),
        )
    )
    return envelope


class OutboxRelay:
    """Publishes unpublished outbox rows. Safe to run in every task thanks to SKIP LOCKED."""

    def __init__(self, db: Database, publisher: Publisher, *, batch_size: int = 100, poll_interval: float = 0.2):
        self._db = db
        self._publisher = publisher
        self._batch_size = batch_size
        self._poll_interval = poll_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="outbox-publish")

    def drain_once(self) -> int:
        """Publish one batch; returns the number of events published."""
        published = 0
        with self._db.session() as session:
            rows = session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.created_at)
                .limit(self._batch_size)
                .with_for_update(skip_locked=True)
            ).all()
            # Publish in chunks of 10 (the SNS PublishBatch limit), a few chunks in parallel.
            chunks = [rows[i : i + 10] for i in range(0, len(rows), 10)]
            results = list(self._pool.map(self._publish_chunk, chunks))
            now = datetime.now(UTC)
            for chunk, failed in zip(chunks, results, strict=True):
                for row in chunk:
                    if str(row.id) in failed:
                        row.attempts += 1
                    else:
                        row.published_at = now
                        published += 1
            session.commit()
        return published

    def _publish_chunk(self, chunk: list[OutboxEvent]) -> set[str]:
        """Returns the ids that could not be published; they stay in the outbox for the next pass."""
        try:
            return self._publisher.publish_batch([row.payload for row in chunk])
        except Exception:  # noqa: BLE001 - keep the rows for the next attempt
            log.warning("outbox publish failed for %d events", len(chunk), exc_info=True)
            return {str(row.id) for row in chunk}

    def drain_all(self) -> int:
        total = 0
        while (count := self.drain_once()) > 0:
            total += count
        return total

    def _run(self) -> None:
        backoff = self._poll_interval
        while not self._stop.is_set():
            try:
                count = self.drain_once()
                backoff = self._poll_interval
                if count >= self._batch_size:
                    continue
            except Exception:  # noqa: BLE001
                log.warning("outbox relay iteration failed", exc_info=True)
                backoff = min(backoff * 2, 5.0)
            self._stop.wait(backoff)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="outbox-relay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
