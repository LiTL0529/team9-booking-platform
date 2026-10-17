import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from platform_common.app_factory import get_session
from platform_common.auth import Principal, current_principal
from platform_common.errors import NotFound

from .models import Notification

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notification_id: uuid.UUID
    kind: str
    title: str
    body: str
    booking_id: uuid.UUID | None
    created_at: datetime
    read_at: datetime | None


class UnreadCount(BaseModel):
    unread: int


@router.get("", response_model=list[NotificationOut], summary="The caller's in-app inbox")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
    principal: Principal = Depends(current_principal),
):
    query = select(Notification).where(Notification.customer_id == principal.sub)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    return session.scalars(query.order_by(Notification.created_at.desc()).limit(limit)).all()


@router.get("/unread-count", response_model=UnreadCount)
def unread_count(session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    count = session.scalar(
        select(func.count()).where(Notification.customer_id == principal.sub, Notification.read_at.is_(None))
    )
    return UnreadCount(unread=count or 0)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: uuid.UUID,
    session: Session = Depends(get_session),
    principal: Principal = Depends(current_principal),
):
    notification = session.get(Notification, notification_id)
    if notification is None or notification.customer_id != principal.sub:
        raise NotFound("notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        session.commit()
    return notification
