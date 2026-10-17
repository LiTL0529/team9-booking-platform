"""Event handlers that build the availability read model.

Events can arrive out of order across queues (for example a BookingConfirmed before the
matching SlotPublished). Booking events carry the full slot snapshot and a slot version,
so the projection can insert a placeholder and later events only move the version forward.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .cache import AvailabilityCache
from .models import MerchantView, SlotView


def _slot_values(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "slot_id": data["slot_id"],
        "merchant_id": data["merchant_id"],
        "resource_id": data["resource_id"],
        "resource_name": data["resource_name"],
        "resource_type": data["resource_type"],
        "start_time": data["start_time"],
        "end_time": data["end_time"],
        "local_date": date.fromisoformat(data["local_date"]),
    }


def build_handlers(cache: AvailabilityCache):
    def invalidate_after_commit(session: Session, day: str, merchant_id: str) -> None:
        session.info.setdefault("after_commit", []).append(lambda: cache.invalidate(day, merchant_id))

    def on_merchant_onboarded(session: Session, envelope: dict[str, Any]) -> None:
        data = envelope["data"]
        stmt = insert(MerchantView).values(merchant_id=data["merchant_id"], name=data["name"], slug=data["slug"])
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["merchant_id"], set_={"name": stmt.excluded.name, "slug": stmt.excluded.slug}
            )
        )

    def on_slot_published(session: Session, envelope: dict[str, Any]) -> None:
        data = envelope["data"]
        values = _slot_values(data)
        stmt = insert(SlotView).values(**values, status="AVAILABLE", version=0)
        # Fill in slot details but never touch status/version, which belong to booking events.
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["slot_id"],
                set_={k: getattr(stmt.excluded, k) for k in values if k != "slot_id"},
            )
        )
        invalidate_after_commit(session, data["local_date"], data["merchant_id"])

    def on_booking_change(status: str):
        def handler(session: Session, envelope: dict[str, Any]) -> None:
            data = envelope["data"]
            stmt = insert(SlotView).values(**_slot_values(data), status=status, version=data["slot_version"])
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["slot_id"],
                    set_={"status": stmt.excluded.status, "version": stmt.excluded.version},
                    where=SlotView.version < stmt.excluded.version,
                )
            )
            invalidate_after_commit(session, data["local_date"], data["merchant_id"])

        return handler

    return {
        "MerchantOnboarded": on_merchant_onboarded,
        "SlotPublished": on_slot_published,
        "BookingConfirmed": on_booking_change("BOOKED"),
        "BookingCancelled": on_booking_change("AVAILABLE"),
    }
