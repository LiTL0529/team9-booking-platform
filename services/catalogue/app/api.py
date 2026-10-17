import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from platform_common.app_factory import get_session
from platform_common.auth import Principal, current_principal, ensure_can_manage_merchant
from platform_common.errors import Conflict, NotFound, Unprocessable
from platform_common.outbox import add_to_outbox

from .models import Resource, TimeSlot

PRODUCER = "catalogue-service"
SLOT_LENGTH = timedelta(hours=1)
MAX_DAYS_PER_REQUEST = 62

resources = APIRouter(prefix="/v1/resources", tags=["resources"])
slots = APIRouter(prefix="/v1/slots", tags=["slots"])


class ResourceCreate(BaseModel):
    merchant_id: uuid.UUID | None = Field(None, description="Defaults to the caller's merchant")
    name: str = Field(min_length=1, max_length=200)
    resource_type: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9_]+$", examples=["badminton_court"])
    description: str = Field("", max_length=2000)
    timezone: str = "Asia/Singapore"

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown timezone") from exc
        return value


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resource_id: uuid.UUID
    merchant_id: uuid.UUID
    name: str
    resource_type: str
    description: str
    timezone: str
    created_at: datetime


class SlotPublish(BaseModel):
    from_date: date
    to_date: date
    start_hour: int = Field(ge=0, le=23, description="First slot start, local time")
    end_hour: int = Field(ge=1, le=24, description="Last slot ends at this hour, local time")
    skip_existing: bool = Field(False, description="Publish only the hours that are still free")

    @model_validator(mode="after")
    def check_range(self):
        if self.to_date < self.from_date:
            raise ValueError("to_date must not be before from_date")
        if (self.to_date - self.from_date).days >= MAX_DAYS_PER_REQUEST:
            raise ValueError(f"at most {MAX_DAYS_PER_REQUEST} days per request")
        if self.end_hour <= self.start_hour:
            raise ValueError("end_hour must be after start_hour")
        return self


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slot_id: uuid.UUID
    resource_id: uuid.UUID
    merchant_id: uuid.UUID
    start_time: datetime
    end_time: datetime
    local_date: date


class SlotDetail(SlotOut):
    resource_name: str
    resource_type: str
    timezone: str


class PublishResult(BaseModel):
    created: int
    skipped_existing: int
    skipped_past: int
    slots: list[SlotOut]


def _resource(session: Session, resource_id: uuid.UUID) -> Resource:
    resource = session.get(Resource, resource_id)
    if resource is None:
        raise NotFound("resource not found")
    return resource


@resources.post("", response_model=ResourceOut, status_code=201, summary="Create a bookable resource")
def create_resource(
    body: ResourceCreate, session: Session = Depends(get_session), principal: Principal = Depends(current_principal)
):
    merchant_id = body.merchant_id or (uuid.UUID(principal.merchant_id) if principal.merchant_id else None)
    if merchant_id is None:
        raise Unprocessable("merchant_id is required")
    ensure_can_manage_merchant(principal, merchant_id)
    resource = Resource(
        resource_id=uuid.uuid4(),
        merchant_id=merchant_id,
        name=body.name,
        resource_type=body.resource_type,
        description=body.description,
        timezone=body.timezone,
        created_by=principal.username,
    )
    session.add(resource)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict(f"resource '{body.name}' already exists for this merchant") from exc
    return resource


@resources.get("", response_model=list[ResourceOut], summary="List a merchant's resources")
def list_resources(merchant_id: uuid.UUID, session: Session = Depends(get_session)):
    return session.scalars(
        select(Resource).where(Resource.merchant_id == merchant_id).order_by(Resource.name)
    ).all()


@resources.get("/{resource_id}", response_model=ResourceOut)
def get_resource(resource_id: uuid.UUID, session: Session = Depends(get_session)):
    return _resource(session, resource_id)


def _candidate_slots(resource: Resource, body: SlotPublish):
    zone = ZoneInfo(resource.timezone)
    day = body.from_date
    while day <= body.to_date:
        for hour in range(body.start_hour, body.end_hour):
            start = datetime(day.year, day.month, day.day, hour, tzinfo=zone).astimezone(UTC)
            yield day, start, start + SLOT_LENGTH
        day += timedelta(days=1)


@resources.post(
    "/{resource_id}/slots",
    response_model=PublishResult,
    status_code=201,
    summary="Publish fixed one-hour slots that do not overlap",
)
def publish_slots(
    resource_id: uuid.UUID,
    body: SlotPublish,
    session: Session = Depends(get_session),
    principal: Principal = Depends(current_principal),
):
    resource = _resource(session, resource_id)
    ensure_can_manage_merchant(principal, resource.merchant_id)
    now = datetime.now(UTC)
    candidates = list(_candidate_slots(resource, body))
    future = [c for c in candidates if c[1] > now]
    if not future:
        raise Unprocessable("all requested slots are in the past")

    # All slots are generated on whole hours, so equal start times are the only possible overlap.
    # The constraints on time_slots are the final guard against concurrent publishers.
    existing = set(
        session.scalars(
            select(TimeSlot.start_time).where(
                TimeSlot.resource_id == resource_id,
                TimeSlot.start_time >= future[0][1],
                TimeSlot.start_time < future[-1][2],
            )
        )
    )
    clashes = [c for c in future if c[1] in existing]
    if clashes and not body.skip_existing:
        raise Conflict(
            f"{len(clashes)} requested slots overlap existing slots",
            code="slot_overlap",
            details={"first_overlap": clashes[0][1].isoformat()},
        )
    created: list[TimeSlot] = []
    for local_date, start, end in future:
        if start in existing:
            continue
        slot = TimeSlot(
            slot_id=uuid.uuid4(),
            resource_id=resource.resource_id,
            merchant_id=resource.merchant_id,
            start_time=start,
            end_time=end,
            local_date=local_date,
        )
        created.append(slot)
        add_to_outbox(
            session,
            "SlotPublished",
            {
                "slot_id": str(slot.slot_id),
                "merchant_id": str(resource.merchant_id),
                "resource_id": str(resource.resource_id),
                "resource_name": resource.name,
                "resource_type": resource.resource_type,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "local_date": local_date.isoformat(),
                "timezone": resource.timezone,
                "capacity": 1,
            },
            PRODUCER,
        )
    session.add_all(created)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict("slots were published concurrently for the same hours, retry", code="slot_overlap") from exc
    return PublishResult(
        created=len(created),
        skipped_existing=len(clashes),
        skipped_past=len(candidates) - len(future),
        slots=created,
    )


@resources.get("/{resource_id}/slots", response_model=list[SlotOut])
def list_slots(
    resource_id: uuid.UUID,
    from_date: date | None = None,
    to_date: date | None = None,
    session: Session = Depends(get_session),
):
    _resource(session, resource_id)
    query = select(TimeSlot).where(TimeSlot.resource_id == resource_id).order_by(TimeSlot.start_time)
    if from_date:
        query = query.where(TimeSlot.local_date >= from_date)
    if to_date:
        query = query.where(TimeSlot.local_date <= to_date)
    return session.scalars(query.limit(2000)).all()


@slots.get("/{slot_id}", response_model=SlotDetail, summary="Slot details (used by the Booking Service)")
def get_slot(slot_id: uuid.UUID, session: Session = Depends(get_session)):
    row = session.execute(
        select(TimeSlot, Resource).join(Resource, Resource.resource_id == TimeSlot.resource_id).where(
            TimeSlot.slot_id == slot_id
        )
    ).first()
    if row is None:
        raise NotFound("slot not found")
    slot, resource = row
    return SlotDetail(
        slot_id=slot.slot_id,
        resource_id=slot.resource_id,
        merchant_id=slot.merchant_id,
        start_time=slot.start_time,
        end_time=slot.end_time,
        local_date=slot.local_date,
        resource_name=resource.name,
        resource_type=resource.resource_type,
        timezone=resource.timezone,
    )
