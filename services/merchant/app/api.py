import logging
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from platform_common.app_factory import get_session
from platform_common.auth import (
    MERCHANT_ADMIN,
    PLATFORM_ADMIN,
    Principal,
    current_principal,
    ensure_can_manage_merchant,
    require_any_role,
)
from platform_common.errors import Conflict, Forbidden, NotFound, ServiceUnavailable
from platform_common.outbox import add_to_outbox
from platform_common.resilience import CircuitOpenError

from .identity import UserNotFound
from .models import Membership, Merchant

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/merchants", tags=["merchants"])
PRODUCER = "merchant-service"


class MerchantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    contact_email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MerchantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    merchant_id: uuid.UUID
    name: str
    slug: str
    contact_email: str
    status: str
    created_at: datetime


class MemberAssign(BaseModel):
    username: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._@+-]+$")
    role: Literal["merchant_admin", "merchant_staff"] = "merchant_staff"


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    membership_id: uuid.UUID
    merchant_id: uuid.UUID
    username: str
    role: str
    sync_status: str
    created_at: datetime


def _get_merchant(session: Session, merchant_id: uuid.UUID) -> Merchant:
    merchant = session.get(Merchant, merchant_id)
    if merchant is None:
        raise NotFound("merchant not found")
    return merchant


@router.post("", response_model=MerchantOut, status_code=201, summary="Onboard a merchant")
def onboard_merchant(
    body: MerchantCreate,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_any_role(PLATFORM_ADMIN)),
):
    merchant = Merchant(merchant_id=uuid.uuid4(), name=body.name, slug=body.slug, contact_email=body.contact_email)
    session.add(merchant)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict(f"merchant slug '{body.slug}' already exists", code="slug_taken") from exc
    add_to_outbox(
        session,
        "MerchantOnboarded",
        {
            "merchant_id": str(merchant.merchant_id),
            "name": merchant.name,
            "slug": merchant.slug,
            "contact_email": merchant.contact_email,
        },
        PRODUCER,
    )
    session.commit()
    log.info("merchant onboarded", extra={"merchant_id": str(merchant.merchant_id), "by": principal.username})
    return merchant


@router.get("", response_model=list[MerchantOut], summary="List merchants visible to the caller")
def list_merchants(session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    query = select(Merchant).order_by(Merchant.created_at)
    if not principal.is_platform_admin:
        if not principal.merchant_id:
            return []
        query = query.where(Merchant.merchant_id == uuid.UUID(principal.merchant_id))
    return session.scalars(query).all()


@router.get("/me", response_model=MerchantOut, summary="The merchant the caller belongs to")
def my_merchant(session: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    if not principal.merchant_id or not principal.is_member_of(principal.merchant_id):
        raise NotFound("you are not a member of any merchant")
    return _get_merchant(session, uuid.UUID(principal.merchant_id))


@router.get("/{merchant_id}", response_model=MerchantOut)
def get_merchant(
    merchant_id: uuid.UUID, session: Session = Depends(get_session), principal: Principal = Depends(current_principal)
):
    ensure_can_manage_merchant(principal, merchant_id)
    return _get_merchant(session, merchant_id)


def _sync(request: Request, session: Session, membership: Membership) -> None:
    directory = request.app.state.identity
    try:
        directory.assign_merchant_role(membership.username, str(membership.merchant_id), membership.role)
    except UserNotFound as exc:
        raise NotFound(f"user '{membership.username}' does not exist in the identity provider") from exc
    except CircuitOpenError:
        log.warning("identity provider circuit open; membership left pending")
        return
    except Exception:  # noqa: BLE001 - leave PENDING, can be retried through the sync endpoint
        log.exception("identity provider sync failed")
        return
    membership.sync_status = "SYNCED"


@router.post(
    "/{merchant_id}/members",
    response_model=MemberOut,
    status_code=201,
    summary="Assign a merchant user and role",
)
def assign_member(
    merchant_id: uuid.UUID,
    body: MemberAssign,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(current_principal),
):
    if not (principal.is_platform_admin or (principal.is_member_of(merchant_id) and MERCHANT_ADMIN in principal.groups)):
        raise Forbidden("only a platform admin or this merchant's admin can assign members")
    _get_merchant(session, merchant_id)
    existing = session.scalar(select(Membership).where(Membership.username == body.username))
    if existing and existing.merchant_id != merchant_id:
        raise Conflict("user already belongs to another merchant", code="user_has_merchant")
    membership = existing or Membership(membership_id=uuid.uuid4(), merchant_id=merchant_id, username=body.username)
    membership.role = body.role
    membership.sync_status = "PENDING"
    session.add(membership)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict("membership changed concurrently, retry") from exc
    try:
        _sync(request, session, membership)
    except NotFound:
        session.rollback()
        raise
    session.commit()
    return membership


@router.get("/{merchant_id}/members", response_model=list[MemberOut])
def list_members(
    merchant_id: uuid.UUID, session: Session = Depends(get_session), principal: Principal = Depends(current_principal)
):
    ensure_can_manage_merchant(principal, merchant_id)
    return session.scalars(
        select(Membership).where(Membership.merchant_id == merchant_id).order_by(Membership.created_at)
    ).all()


@router.post("/{merchant_id}/members/{username}/sync", response_model=MemberOut, summary="Retry a pending sync")
def resync_member(
    merchant_id: uuid.UUID,
    username: str,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_any_role(PLATFORM_ADMIN, MERCHANT_ADMIN)),
):
    ensure_can_manage_merchant(principal, merchant_id)
    membership = session.scalar(
        select(Membership).where(Membership.merchant_id == merchant_id, Membership.username == username)
    )
    if membership is None:
        raise NotFound("membership not found")
    _sync(request, session, membership)
    session.commit()
    if membership.sync_status != "SYNCED":
        raise ServiceUnavailable("identity provider is unavailable, try again later")
    return membership
