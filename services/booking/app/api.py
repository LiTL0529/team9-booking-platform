import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from platform_common.app_factory import get_session
from platform_common.auth import CUSTOMER, Principal, current_principal, ensure_can_manage_merchant, require_any_role
from platform_common.errors import Forbidden, NotFound

from . import domain
from .models import Booking, SlotInventory

router = APIRouter(prefix="/v1/bookings", tags=["bookings"])


class BookingCreate(BaseModel):
    slot_id: uuid.UUID


class BookingOut(BaseModel):
    booking_id: uuid.UUID
    reference: str
    status: str
    slot_id: uuid.UUID
    merchant_id: uuid.UUID
    resource_id: uuid.UUID
    resource_name: str
    resource_type: str
    start_time: datetime
    end_time: datetime
    local_date: date
    customer_username: str
    created_at: datetime
    cancelled_at: datetime | None

    @classmethod
    def of(cls, booking: Booking) -> "BookingOut":
        slot = booking.slot
        return cls(
            booking_id=booking.booking_id,
            reference=booking.reference,
            status=booking.status,
            slot_id=booking.slot_id,
            merchant_id=booking.merchant_id,
            resource_id=slot.resource_id,
            resource_name=slot.resource_name,
            resource_type=slot.resource_type,
            start_time=slot.start_time,
            end_time=slot.end_time,
            local_date=slot.local_date,
            customer_username=booking.customer_username,
            created_at=booking.created_at,
            cancelled_at=booking.cancelled_at,
        )


@router.post(
    "",
    response_model=BookingOut,
    status_code=201,
    summary="Reserve an available slot",
    responses={200: {"description": "Replay of an earlier request with the same Idempotency-Key"},
               409: {"description": "The slot is already booked"}},
)
def create_booking(
    body: BookingCreate,
    request: Request,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_any_role(CUSTOMER)),
):
    booking, replayed = domain.create_booking(
        session, principal, body.slot_id, idempotency_key, request.app.state.catalogue
    )
    if replayed:
        response.status_code = 200
        response.headers["Idempotent-Replay"] = "true"
    response.headers["Location"] = f"/v1/bookings/{booking.booking_id}"
    return BookingOut.of(booking)


@router.get("", response_model=list[BookingOut], summary="The caller's bookings, or a merchant's bookings")
def list_bookings(
    merchant_id: uuid.UUID | None = Query(None, description="Merchant users: list their merchant's bookings"),
    status: Literal["CONFIRMED", "CANCELLED"] | None = None,
    from_date: date | None = None,
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_session),
    principal: Principal = Depends(current_principal),
):
    query = select(Booking)
    if merchant_id is not None:
        ensure_can_manage_merchant(principal, merchant_id)
        query = query.where(Booking.merchant_id == merchant_id)
    else:
        query = query.where(Booking.customer_id == principal.sub)
    if status:
        query = query.where(Booking.status == status)
    if from_date:
        query = query.join(SlotInventory, SlotInventory.slot_id == Booking.slot_id).where(
            SlotInventory.local_date >= from_date
        )
    query = query.order_by(Booking.created_at.desc()).limit(limit)
    return [BookingOut.of(b) for b in session.scalars(query).unique()]


@router.get("/{booking_id}", response_model=BookingOut)
def get_booking(
    booking_id: uuid.UUID, session: Session = Depends(get_session), principal: Principal = Depends(current_principal)
):
    booking = session.get(Booking, booking_id)
    if booking is None:
        raise NotFound("booking not found")
    if booking.customer_id != principal.sub and not principal.can_manage_merchant(booking.merchant_id):
        raise Forbidden("not your booking")
    return BookingOut.of(booking)


@router.post("/{booking_id}/cancel", response_model=BookingOut, summary="Cancel a future booking")
def cancel_booking(
    booking_id: uuid.UUID, session: Session = Depends(get_session), principal: Principal = Depends(current_principal)
):
    return BookingOut.of(domain.cancel_booking(session, principal, booking_id))
