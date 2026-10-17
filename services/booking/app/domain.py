"""Booking rules. All consistency decisions stay inside this service.

A booking is one local transaction: mark the slot as taken (conditional UPDATE), insert the
booking and stage the BookingConfirmed event in the outbox. Concurrent requests for the
same slot serialise on the slot row; the loser's UPDATE matches no row and gets a 409.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from platform_common.auth import Principal
from platform_common.errors import Conflict, Forbidden, NotFound, ServiceUnavailable, Unprocessable
from platform_common.outbox import add_to_outbox
from platform_common.resilience import CircuitOpenError, ResilientClient, RetryableError

from .models import Booking, SlotInventory

log = logging.getLogger(__name__)
PRODUCER = "booking-service"
_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_reference() -> str:
    return "BK-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(8))


class CatalogueClient:
    """Read-through to the Catalogue Service for slots whose event has not arrived yet."""

    def __init__(self, client: ResilientClient):
        self._client = client

    def fetch_slot(self, slot_id: uuid.UUID) -> dict[str, Any] | None:
        try:
            response = self._client.get(f"/v1/slots/{slot_id}")
        except (CircuitOpenError, RetryableError) as exc:
            raise ServiceUnavailable("slot details are temporarily unavailable, retry shortly") from exc
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()


def upsert_inventory(session: Session, data: dict[str, Any]) -> None:
    """Add a slot to the inventory. Re-delivered or late events never overwrite booking state."""
    session.execute(
        insert(SlotInventory)
        .values(
            slot_id=data["slot_id"],
            merchant_id=data["merchant_id"],
            resource_id=data["resource_id"],
            resource_name=data["resource_name"],
            resource_type=data["resource_type"],
            start_time=data["start_time"],
            end_time=data["end_time"],
            local_date=date.fromisoformat(str(data["local_date"])),
            status="AVAILABLE",
            version=0,
        )
        .on_conflict_do_nothing(index_elements=["slot_id"])
    )


def event_data(booking: Booking, slot: SlotInventory) -> dict[str, Any]:
    data = {
        "booking_id": str(booking.booking_id),
        "reference": booking.reference,
        "slot_id": str(slot.slot_id),
        "slot_version": slot.version,
        "customer_id": booking.customer_id,
        "customer_username": booking.customer_username,
        "merchant_id": str(slot.merchant_id),
        "resource_id": str(slot.resource_id),
        "resource_name": slot.resource_name,
        "resource_type": slot.resource_type,
        "start_time": slot.start_time.isoformat(),
        "end_time": slot.end_time.isoformat(),
        "local_date": slot.local_date.isoformat(),
    }
    if booking.cancelled_at:
        data["cancelled_at"] = booking.cancelled_at.isoformat()
    return data


def _by_idempotency_key(session: Session, customer_id: str, key: str) -> Booking | None:
    return session.scalar(select(Booking).where(Booking.customer_id == customer_id, Booking.idempotency_key == key))


def _replay(existing: Booking, slot_id: uuid.UUID) -> tuple[Booking, bool]:
    if existing.slot_id != slot_id:
        raise Unprocessable("Idempotency-Key was already used for a different slot", code="idempotency_key_reused")
    return existing, True


def create_booking(
    session: Session, principal: Principal, slot_id: uuid.UUID, idempotency_key: str, catalogue: CatalogueClient
) -> tuple[Booking, bool]:
    """Returns (booking, replayed)."""
    existing = _by_idempotency_key(session, principal.sub, idempotency_key)
    if existing:
        return _replay(existing, slot_id)

    start_time = session.scalar(select(SlotInventory.start_time).where(SlotInventory.slot_id == slot_id))
    if start_time is None:
        detail = catalogue.fetch_slot(slot_id)
        if detail is None:
            raise NotFound("slot not found")
        upsert_inventory(session, detail)
        session.commit()
        start_time = session.scalar(select(SlotInventory.start_time).where(SlotInventory.slot_id == slot_id))
    if start_time <= utcnow():
        raise Unprocessable("slot has already started", code="slot_in_past")

    now = utcnow()
    slot = session.scalars(
        update(SlotInventory)
        .where(SlotInventory.slot_id == slot_id, SlotInventory.status == "AVAILABLE")
        .values(status="BOOKED", version=SlotInventory.version + 1, updated_at=now)
        .returning(SlotInventory),
        execution_options={"populate_existing": True},
    ).first()
    if slot is None:
        session.rollback()
        raise Conflict("slot is already booked", code="slot_taken")

    booking = Booking(
        booking_id=uuid.uuid4(),
        reference=new_reference(),
        slot_id=slot.slot_id,
        merchant_id=slot.merchant_id,
        customer_id=principal.sub,
        customer_username=principal.username,
        status="CONFIRMED",
        idempotency_key=idempotency_key,
        created_at=now,
    )
    booking.slot = slot
    session.add(booking)
    add_to_outbox(session, "BookingConfirmed", event_data(booking, slot), PRODUCER)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = _by_idempotency_key(session, principal.sub, idempotency_key)
        if existing:
            return _replay(existing, slot_id)
        raise Conflict("slot is already booked", code="slot_taken") from None
    log.info("booking confirmed", extra={"booking_id": str(booking.booking_id), "slot_id": str(slot_id)})
    return booking, False


def cancel_booking(session: Session, principal: Principal, booking_id: uuid.UUID) -> Booking:
    booking = session.scalars(
        select(Booking).where(Booking.booking_id == booking_id).with_for_update(of=Booking)
    ).first()
    if booking is None:
        raise NotFound("booking not found")
    if booking.customer_id != principal.sub and not principal.is_platform_admin:
        raise Forbidden("you can only cancel your own bookings")
    if booking.status != "CONFIRMED":
        raise Conflict("booking is already cancelled", code="already_cancelled")
    if booking.slot.start_time <= utcnow():
        raise Unprocessable("bookings can only be cancelled before the slot starts", code="slot_in_past")

    now = utcnow()
    booking.status = "CANCELLED"
    booking.cancelled_at = now
    slot = session.scalars(
        update(SlotInventory)
        .where(SlotInventory.slot_id == booking.slot_id)
        .values(status="AVAILABLE", version=SlotInventory.version + 1, updated_at=now)
        .returning(SlotInventory),
        execution_options={"populate_existing": True},
    ).one()
    add_to_outbox(session, "BookingCancelled", event_data(booking, slot), PRODUCER)
    session.commit()
    log.info("booking cancelled", extra={"booking_id": str(booking.booking_id)})
    return booking


def on_slot_published(session: Session, envelope: dict[str, Any]) -> None:
    upsert_inventory(session, envelope["data"])
