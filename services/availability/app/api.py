import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from platform_common.app_factory import get_session

from .models import MerchantView, SlotView

router = APIRouter(prefix="/v1/availability", tags=["availability"])
MAX_RESULTS = 1000


class MerchantSummary(BaseModel):
    merchant_id: uuid.UUID
    name: str
    slug: str


class SlotSummary(BaseModel):
    slot_id: uuid.UUID
    merchant_id: uuid.UUID
    merchant_name: str
    resource_id: uuid.UUID
    resource_name: str
    resource_type: str
    start_time: datetime
    end_time: datetime
    status: str


class SlotSearchResult(BaseModel):
    date: date
    count: int
    offset: int
    has_more: bool
    slots: list[SlotSummary]


@router.get("/merchants", response_model=list[MerchantSummary], summary="Participating merchants")
def list_merchants(session: Session = Depends(get_session)):
    return [
        MerchantSummary(merchant_id=m.merchant_id, name=m.name, slug=m.slug)
        for m in session.scalars(select(MerchantView).order_by(MerchantView.name))
    ]


@router.get("/resource-types", response_model=list[str], summary="Resource types that have slots")
def list_resource_types(session: Session = Depends(get_session)):
    return list(session.scalars(select(SlotView.resource_type).distinct().order_by(SlotView.resource_type)))


@router.get("/slots", response_model=SlotSearchResult, summary="Search slots across all merchants")
def search_slots(
    request: Request,
    date_: date = Query(..., alias="date", description="Local date of the slots"),
    merchant_id: uuid.UUID | None = None,
    resource_type: str | None = Query(None, max_length=50),
    include_booked: bool = False,
    limit: int = Query(200, ge=1, le=MAX_RESULTS),
    offset: int = Query(0, ge=0, le=100_000),
    session: Session = Depends(get_session),
):
    cache = request.app.state.cache
    day = date_.isoformat()
    key, cached = cache.get(day, merchant_id, (resource_type, int(include_booked), limit, offset))
    if cached is not None:
        # Popular searches are served straight from the cache as pre-serialised JSON.
        return Response(content=cached, media_type="application/json", headers={"X-Cache": "HIT"})

    query = (
        select(SlotView, func.coalesce(MerchantView.name, "Unknown merchant"))
        .outerjoin(MerchantView, MerchantView.merchant_id == SlotView.merchant_id)
        .where(SlotView.local_date == date_)
        .order_by(SlotView.start_time, MerchantView.name, SlotView.resource_name, SlotView.slot_id)
        .offset(offset)
        .limit(limit + 1)
    )
    if merchant_id:
        query = query.where(SlotView.merchant_id == merchant_id)
    if resource_type:
        query = query.where(SlotView.resource_type == resource_type)
    if not include_booked:
        query = query.where(SlotView.status == "AVAILABLE")
    slots = [
        SlotSummary(
            slot_id=s.slot_id,
            merchant_id=s.merchant_id,
            merchant_name=name,
            resource_id=s.resource_id,
            resource_name=s.resource_name,
            resource_type=s.resource_type,
            start_time=s.start_time,
            end_time=s.end_time,
            status=s.status,
        )
        for s, name in session.execute(query)
    ]
    page = slots[:limit]
    body = SlotSearchResult(
        date=date_, count=len(page), offset=offset, has_more=len(slots) > limit, slots=page
    ).model_dump_json().encode()
    cache.put(key, body)
    return Response(
        content=body, media_type="application/json", headers={"X-Cache": "MISS" if cache.enabled else "DISABLED"}
    )
