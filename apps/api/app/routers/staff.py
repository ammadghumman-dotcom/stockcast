"""Staff-only beta program admin (STAFF_EMAILS). Everyone else gets 404, so it stays invisible."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.deps import DB, AuthContext, Ctx
from app.services import audit
from app.services import beta as beta_svc
from app.services.waitlist import beta_fit

router = APIRouter(prefix="/staff", tags=["staff"])


def require_staff(ctx: Ctx) -> AuthContext:
    if not beta_svc.is_staff(ctx.email):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return ctx


Staff = Annotated[AuthContext, Depends(require_staff)]


class StaffMe(BaseModel):
    staff: bool


class WaitlistRow(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    company: str | None
    website: str | None
    channels: list[str]
    makes_products: bool
    notes: str | None
    source: str
    beta_fit: bool
    invited_at: datetime | None
    created_at: datetime


class InviteIn(BaseModel):
    emails: list[str] = Field(min_length=1, max_length=50)
    resend: bool = False


class InviteOut(BaseModel):
    sent: list[str]
    skipped: list[str]
    failed: list[str]
    unknown: list[str]


class GrantIn(BaseModel):
    key: str = Field(min_length=2, max_length=320, description="workspace slug, shop or email")
    on: bool = True


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    is_beta: bool
    plan: str


class FeedbackRow(BaseModel):
    id: uuid.UUID
    created_at: datetime
    workspace: str | None
    actor: str
    rating: int | None
    page: str | None
    message: str


@router.get("/me", response_model=StaffMe)
def staff_me(ctx: Ctx) -> StaffMe:
    return StaffMe(staff=beta_svc.is_staff(ctx.email))


@router.get("/beta/waitlist", response_model=list[WaitlistRow])
def beta_waitlist(db: DB, ctx: Staff, all: bool = False) -> list[WaitlistRow]:  # noqa: A002
    return [
        WaitlistRow(
            id=r.id,
            email=r.email,
            name=r.name,
            company=r.company,
            website=r.website,
            channels=list(r.channels or []),
            makes_products=r.makes_products,
            notes=r.notes,
            source=r.source,
            beta_fit=beta_fit(r.channels, r.makes_products),
            invited_at=r.beta_invited_at,
            created_at=r.created_at,
        )
        for r in beta_svc.waitlist(db, include_all=all)
    ]


@router.post("/beta/invites", response_model=InviteOut)
def beta_invite(db: DB, ctx: Staff, body: InviteIn) -> InviteOut:
    out = beta_svc.send_invites(db, body.emails, resend=body.resend)
    audit.record(
        db, ctx, action="staff.beta_invite", entity="waitlist", after={k: v for k, v in out.items()}
    )
    db.commit()
    return InviteOut(**out)


def _ws(org) -> WorkspaceOut:
    return WorkspaceOut(id=org.id, name=org.name, slug=org.slug, is_beta=org.is_beta, plan=org.plan)


@router.post("/beta/grant", response_model=WorkspaceOut)
def beta_grant(db: DB, ctx: Staff, body: GrantIn) -> WorkspaceOut:
    org = beta_svc.find_org(db, body.key)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No workspace found for {body.key!r}")
    before = {"is_beta": org.is_beta}
    org = beta_svc.set_beta(db, body.key, body.on)
    assert org is not None
    audit.record(
        db,
        ctx,
        action="staff.beta_grant",
        entity="organization",
        entity_id=org.id,
        before=before,
        after={"is_beta": org.is_beta, "workspace": org.slug},
    )
    db.commit()
    return _ws(org)


@router.get("/beta/workspaces", response_model=list[WorkspaceOut])
def beta_workspaces(db: DB, ctx: Staff) -> list[WorkspaceOut]:
    return [_ws(o) for o in beta_svc.beta_workspaces(db)]


@router.get("/beta/feedback", response_model=list[FeedbackRow])
def beta_feedback(db: DB, ctx: Staff, days: int = Query(14, ge=1, le=365)) -> list[FeedbackRow]:
    return [
        FeedbackRow(
            id=fb.id,
            created_at=fb.created_at,
            workspace=name,
            actor=fb.actor,
            rating=fb.rating,
            page=fb.page,
            message=fb.message,
        )
        for fb, name in beta_svc.recent_feedback(db, days)
    ]
