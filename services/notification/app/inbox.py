import time
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .models import Notification

DISPLAY_ZONE = ZoneInfo("Asia/Singapore")


def _when(data: dict[str, Any]) -> str:
    start = datetime.fromisoformat(data["start_time"]).astimezone(DISPLAY_ZONE)
    return start.strftime("%a %d %b %Y, %H:%M")


def build_handlers(processing_delay_ms: int = 0):
    def write(session: Session, envelope: dict[str, Any], kind: str, title: str, body: str) -> None:
        if processing_delay_ms:
            # Simulates the cost of a real delivery channel (e-mail/SMS) for the backlog test.
            time.sleep(processing_delay_ms / 1000)
        data = envelope["data"]
        session.add(
            Notification(
                notification_id=uuid.uuid4(),
                customer_id=data["customer_id"],
                kind=kind,
                title=title,
                body=body,
                booking_id=uuid.UUID(data["booking_id"]),
                source_event_id=uuid.UUID(envelope["event_id"]),
            )
        )

    def on_confirmed(session: Session, envelope: dict[str, Any]) -> None:
        d = envelope["data"]
        write(
            session,
            envelope,
            "BOOKING_CONFIRMED",
            f"Booking {d['reference']} confirmed",
            f"{d['resource_name']} is reserved for you on {_when(d)}.",
        )

    def on_cancelled(session: Session, envelope: dict[str, Any]) -> None:
        d = envelope["data"]
        write(
            session,
            envelope,
            "BOOKING_CANCELLED",
            f"Booking {d['reference']} cancelled",
            f"Your booking of {d['resource_name']} on {_when(d)} has been cancelled.",
        )

    return {"BookingConfirmed": on_confirmed, "BookingCancelled": on_cancelled}
