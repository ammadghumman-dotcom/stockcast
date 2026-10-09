"""Team membership: invite, change role, remove — with owner protection.

Rules (enforced here, the UI only mirrors them):
- A workspace has one owner. Only the owner can hand ownership to someone else; nobody can
  remove the owner or change the owner's role (transfer first).
- Invites are for Admin or Viewer.
- In Clerk mode every change is written to Clerk first (invitation, membership role, removal),
  because Clerk's session token decides the role on the next request.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import AuthContext
from app.models import Organization, User
from app.services import audit, clerk

FIELDS = ("email", "name", "role", "external_auth_id", "clerk_invitation_id")


def _fail(code: int, msg: str) -> HTTPException:
    return HTTPException(code, msg)


def _clerk_org(db: Session, ctx: AuthContext) -> str | None:
    """The Clerk org id when this workspace is managed in Clerk, else None (header mode)."""
    if ctx.mode != "clerk":
        return None
    org = db.get(Organization, ctx.org_id)
    if org is None or not org.clerk_org_id:
        return None
    if not clerk.enabled():
        raise _fail(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Team changes need CLERK_SECRET_KEY on the API so they can be saved in Clerk.",
        )
    return org.clerk_org_id


def _actor(db: Session, ctx: AuthContext) -> User | None:
    return db.get(User, ctx.user_id) if ctx.user_id else None


def _clerk(call, *args, **kwargs):  # type: ignore[no-untyped-def]
    try:
        return call(*args, **kwargs)
    except clerk.ClerkError as exc:
        code = status.HTTP_409_CONFLICT if exc.status in (400, 409, 422) else 502
        raise _fail(code, f"Clerk: {exc}") from exc


def invite(db: Session, ctx: AuthContext, *, email: str, name: str, role: str) -> User:
    ctx.require("admin")
    if role not in ("admin", "viewer"):
        raise _fail(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Invite people as Admin or Viewer. Ownership is transferred from the owner's row.",
        )
    exists = db.scalar(
        select(User.id).where(User.org_id == ctx.org_id, func.lower(User.email) == email.lower())
    )
    if exists:
        raise _fail(status.HTTP_409_CONFLICT, f"{email} is already on this team.")
    user = User(org_id=ctx.org_id, email=email, name=name, role=role)
    clerk_org = _clerk_org(db, ctx)
    if clerk_org:
        actor = _actor(db, ctx)
        inv = _clerk(
            clerk.invite,
            clerk_org,
            email,
            role,
            inviter=actor.external_auth_id if actor else None,
            redirect_url=f"{settings.web_base_url.rstrip('/')}/sign-up",
        )
        user.clerk_invitation_id = inv.get("id")
    db.add(user)
    db.flush()
    audit.record(
        db,
        ctx,
        action="team.invite",
        entity="user",
        entity_id=user.id,
        after=audit.snapshot(user, FIELDS),
    )
    db.commit()
    db.refresh(user)
    return user


def change_role(db: Session, ctx: AuthContext, user_id: uuid.UUID, role: str) -> User:
    ctx.require("admin")
    user = _get(db, ctx, user_id)
    if role == user.role:
        return user
    before = audit.snapshot(user, FIELDS)
    clerk_org = _clerk_org(db, ctx)
    if role == "owner":
        if ctx.role != "owner":
            raise _fail(status.HTTP_403_FORBIDDEN, "Only the owner can transfer ownership.")
        if user.status == "invited":
            raise _fail(
                status.HTTP_409_CONFLICT, "Ownership can go only to someone who has signed in."
            )
        if clerk_org and user.external_auth_id:
            _clerk(clerk.set_member_role, clerk_org, user.external_auth_id, "owner")
        user.role = "owner"
        for prev in db.scalars(
            select(User).where(User.org_id == ctx.org_id, User.role == "owner", User.id != user.id)
        ):
            prev.role = "admin"  # stays org:admin in Clerk
    else:
        if user.role == "owner":
            raise _fail(
                status.HTTP_403_FORBIDDEN,
                "The owner's role can't be changed. Transfer ownership to someone else first.",
            )
        if clerk_org and user.external_auth_id:
            _clerk(clerk.set_member_role, clerk_org, user.external_auth_id, role)
        user.role = role
    audit.record(
        db,
        ctx,
        action="team.role",
        entity="user",
        entity_id=user.id,
        before=before,
        after=audit.snapshot(user, FIELDS),
    )
    db.commit()
    db.refresh(user)
    return user


def rename(db: Session, ctx: AuthContext, user_id: uuid.UUID, name: str) -> User:
    ctx.require("admin")
    user = _get(db, ctx, user_id)
    user.name = name
    db.commit()
    db.refresh(user)
    return user


def remove(db: Session, ctx: AuthContext, user_id: uuid.UUID) -> None:
    ctx.require("admin")
    user = _get(db, ctx, user_id)
    if user.role == "owner":
        raise _fail(
            status.HTTP_403_FORBIDDEN,
            "The owner can't be removed. Transfer ownership to someone else first.",
        )
    clerk_org = _clerk_org(db, ctx)
    if clerk_org:
        if user.external_auth_id:
            _clerk(clerk.remove_member, clerk_org, user.external_auth_id)
        elif user.clerk_invitation_id:
            actor = _actor(db, ctx)
            _clerk(
                clerk.revoke_invitation,
                clerk_org,
                user.clerk_invitation_id,
                requester=actor.external_auth_id if actor else None,
            )
    audit.record(
        db,
        ctx,
        action="team.remove",
        entity="user",
        entity_id=user.id,
        before=audit.snapshot(user, FIELDS),
    )
    db.delete(user)
    db.commit()


def _get(db: Session, ctx: AuthContext, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None or user.org_id != ctx.org_id:
        raise _fail(status.HTTP_404_NOT_FOUND, "Team member not found")
    return user
