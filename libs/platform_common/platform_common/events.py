"""Event envelope used on the event bus.

Every event has the same envelope so that consumers can de-duplicate on event_id and
continue the trace that produced it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from opentelemetry import propagate


def new_envelope(event_type: str, data: dict[str, Any], producer: str, *, version: int = 1) -> dict[str, Any]:
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "event_version": version,
        "occurred_at": datetime.now(UTC).isoformat(),
        "producer": producer,
        "trace": carrier,
        "data": data,
    }
