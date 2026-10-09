"""Request authentication and org scoping.

Two modes (settings.auth_mode):
  clerk  — `Authorization: Bearer <Clerk session JWT>` verified against the Clerk JWKS. The
           token's `org_id` / `org_role` / `sub` map to our Organization / User / role, and
           both are provisioned on first sight.
  header — `X-Org-Id: <uuid>` (dev, e2e, CSV-only setups). Never enable in production.

Every data route depends on `OrgId` (org-scoped uuid) or `Ctx` (org + user + role). Viewers
are read-only: any non-GET request from a viewer is rejected here, centrally, so no route can
forget to check.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Organization, PlanningSettings, Region, User

DB = Annotated[Session, Depends(get_db)]

ROLE_RANK = {"viewer": 0, "admin": 1, "owner": 2}
CLERK_ROLE_MAP = {"org:owner": "owner", "org:admin": "admin", "org:member": "viewer"}
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class AuthContext:
    org_id: uuid.UUID
    user_id: uuid.UUID | None
    role: str
    email: str | None = None
    mode: str = "header"

    @property
    def actor(self) -> str:
        return self.email or (str(self.user_id) if self.user_id else "system")

    def require(self, role: str) -> None:
        if ROLE_RANK.get(self.role, -1) < ROLE_RANK[role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires {role} role")


# --------------------------------------------------------------------------- Clerk JWT
CLOCK_LEEWAY_S = 30  # Clerk session tokens live 60 s; tolerate clock skew between hosts


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True)


def verify_clerk_token(token: str) -> dict:
    if not settings.clerk_jwks_url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "CLERK_JWKS_URL not configured")
    try:
        key = _jwks_client(settings.clerk_jwks_url).get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer or None,
            options={"require": ["sub", "exp"], "verify_aud": False},
            leeway=CLOCK_LEEWAY_S,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {exc}") from exc


def _clerk_fetch(path: str) -> dict | None:
    """Best-effort lookup via the Clerk Backend API (needs CLERK_SECRET_KEY)."""
    from app.services import clerk

    return clerk.get(path)


def org_claims(claims: dict) -> tuple[str | None, str]:
    """(clerk org id, clerk org role) from a session token.

    Clerk's v1 tokens carry `org_id` / `org_role`; v2 tokens nest them as `o: {id, rol}` with
    the role unprefixed ("admin"). Both are accepted so a token-format change on Clerk's side
    never locks every user out again."""
    raw = claims.get("o")
    o: dict = raw if isinstance(raw, dict) else {}
    org_id = claims.get("org_id") or o.get("id")
    role = claims.get("org_role") or o.get("rol") or ""
    if role and not role.startswith("org:"):
        role = f"org:{role}"
    return org_id, role


PLACEHOLDER_EMAIL_DOMAIN = "@clerk.local"
_REFRESH_EVERY_S = 600
_last_refresh: dict[str, float] = {}


def _due(key: str) -> bool:
    """Rate-limit best-effort Clerk lookups to one per key per 10 minutes per process."""
    import time

    now = time.monotonic()
    if now - _last_refresh.get(key, -_REFRESH_EVERY_S) < _REFRESH_EVERY_S:
        return False
    _last_refresh[key] = now
    return True


def create_org(db: Session, *, name: str, slug_base: str, **fields: Any) -> Organization:
    """New workspace on the trial with its default region, planning settings and holidays."""
    slug_base = re.sub(r"[^a-z0-9-]+", "-", slug_base.lower()).strip("-") or "workspace"
    slug, n = slug_base, 1
    while db.scalar(select(Organization.id).where(Organization.slug == slug)):
        n += 1
        slug = f"{slug_base}-{n}"
    org = Organization(
        name=name,
        slug=slug,
        plan="trial",
        plan_status="trialing",
        trial_ends_at=datetime.now(UTC) + timedelta(days=settings.trial_days),
        **fields,
    )
    db.add(org)
    db.flush()
    region = Region(org_id=org.id, code="US", name="United States", currency="USD")
    db.add(region)
    db.add(PlanningSettings(org_id=org.id))
    db.flush()
    from app.forecast.holidays_seed import seed_region_holidays

    seed_region_holidays(db, org.id, region)
    db.commit()
    return org


def provision_org(
    db: Session, clerk_org_id: str, name: str | None = None
) -> tuple[Organization, bool]:
    """Return (org, created). Creates org + default region/settings on first sight."""
    org = db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if org:
        if org.name == f"Workspace {clerk_org_id[-6:]}" and _due(f"org:{clerk_org_id}"):
            info = _clerk_fetch(f"/organizations/{clerk_org_id}")
            if info and info.get("name"):
                org.name = info["name"]
                db.commit()
        return org, False
    info = _clerk_fetch(f"/organizations/{clerk_org_id}")
    name = name or (info or {}).get("name") or f"Workspace {clerk_org_id[-6:]}"
    slug_base = (info or {}).get("slug") or clerk_org_id[-12:].lower()
    return create_org(db, name=name, slug_base=slug_base, clerk_org_id=clerk_org_id), True


def _clerk_identity(sub: str, claims: dict) -> tuple[str | None, str | None]:
    email = claims.get("email")
    name = claims.get("name") or claims.get("first_name")
    if not email or not name:
        info = _clerk_fetch(f"/users/{sub}") or {}
        from app.services.clerk import primary_email

        email = email or primary_email(info)
        full = f"{info.get('first_name') or ''} {info.get('last_name') or ''}".strip()
        name = name or full or None
    return email, name


def _is_creator(org: Organization, sub: str) -> bool:
    if not org.clerk_org_id:
        return False
    info = _clerk_fetch(f"/organizations/{org.clerk_org_id}") or {}
    return info.get("created_by") == sub


def _has_owner(db: Session, org: Organization) -> bool:
    return (
        db.scalar(select(User.id).where(User.org_id == org.id, User.role == "owner").limit(1))
        is not None
    )


def _sync_role(current: str, clerk_role: str) -> str:
    """Clerk decides admin vs viewer; Stockcast keeps 'owner' on top of an org:admin."""
    if current == "owner" and clerk_role == "admin":
        return "owner"
    return clerk_role


def provision_user(
    db: Session, org: Organization, claims: dict, role: str, *, org_created: bool = False
) -> User:
    """Find or create the Stockcast user behind a Clerk session.

    - An invited row (same email, not yet linked) is claimed instead of adding a duplicate.
    - The workspace creator becomes owner (Clerk only knows admin and member).
    - A placeholder email from an earlier failed Clerk lookup is repaired when possible."""
    sub = claims["sub"]
    user = db.scalar(select(User).where(User.org_id == org.id, User.external_auth_id == sub))
    if user:
        changed = False
        new_role = _sync_role(user.role, role)
        if new_role != user.role:
            user.role, changed = new_role, True
        placeholder = user.email.endswith(PLACEHOLDER_EMAIL_DOMAIN) or user.name.endswith(
            PLACEHOLDER_EMAIL_DOMAIN
        )
        if placeholder and _due(f"user:{sub}"):
            email, name = _clerk_identity(sub, claims)
            if (
                email
                and user.email.endswith(PLACEHOLDER_EMAIL_DOMAIN)
                and not _email_taken(db, org, email, user.id)
            ):
                user.email, changed = email, True
            if user.name.endswith(PLACEHOLDER_EMAIL_DOMAIN) and not user.email.endswith(
                PLACEHOLDER_EMAIL_DOMAIN
            ):
                user.name, changed = name or user.email, True
        # rows created before owners existed: the workspace creator is promoted once
        if (
            user.role == "admin"
            and not _has_owner(db, org)
            and _due(f"owner:{org.id}:{sub}")
            and _is_creator(org, sub)
        ):
            user.role, changed = "owner", True
        if changed:
            db.commit()
        return user

    email, name = _clerk_identity(sub, claims)
    invited = (
        db.scalar(
            select(User).where(
                User.org_id == org.id,
                User.external_auth_id.is_(None),
                func.lower(User.email) == email.lower(),
            )
        )
        if email
        else None
    )
    if (
        role == "admin"
        and (org_created or not _has_owner(db, org))
        and (org_created or _is_creator(org, sub))
    ):
        role = "owner"
    if invited:
        invited.external_auth_id = sub
        invited.role = role
        invited.clerk_invitation_id = None
        if name and not invited.name:
            invited.name = name
        db.commit()
        return invited
    email = email or f"{sub}{PLACEHOLDER_EMAIL_DOMAIN}"
    user = User(org_id=org.id, email=email, name=name or email, role=role, external_auth_id=sub)
    db.add(user)
    db.commit()
    return user


def _email_taken(db: Session, org: Organization, email: str, except_id: uuid.UUID) -> bool:
    return (
        db.scalar(
            select(User.id).where(
                User.org_id == org.id, func.lower(User.email) == email.lower(), User.id != except_id
            )
        )
        is not None
    )


# --------------------------------------------------------------------------- dependency
def _is_shopify_session_token(token: str) -> bool:
    """App Bridge ID tokens carry `dest` (the shop admin URL); Clerk tokens never do."""
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return False
    return isinstance(claims.get("dest"), str) and ".myshopify.com" in claims["dest"]


def get_auth(
    request: Request,
    db: DB,
    authorization: Annotated[str | None, Header()] = None,
    x_org_id: Annotated[str | None, Header(alias="X-Org-Id")] = None,
) -> AuthContext:
    bearer = (
        authorization.removeprefix("Bearer ").strip()
        if authorization and authorization.startswith("Bearer ")
        else None
    )
    if bearer and _is_shopify_session_token(bearer):
        # Embedded in the Shopify admin: the App Bridge ID token names the shop; the staff
        # member who can open the app owns its workspace.
        from app.ingest.shopify.oauth import InvalidSessionToken, verify_session_token
        from app.services.shopify_app import org_for_shop

        try:
            claims = verify_session_token(bearer)
        except InvalidSessionToken as exc:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                str(exc),
                headers={"X-Shopify-Retry-Invalid-Session-Request": "1"},
            ) from exc
        org, _ = org_for_shop(db, claims["shop"])
        ctx = AuthContext(org.id, None, "owner", None, "shopify")
        request.state.auth = ctx
        return ctx
    if settings.auth_mode == "clerk" or bearer:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bearer token required")
        claims = verify_clerk_token(authorization.removeprefix("Bearer ").strip())
        clerk_org, clerk_role = org_claims(claims)
        if not clerk_org:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "select an organization first")
        role = CLERK_ROLE_MAP.get(clerk_role, "viewer")
        org, created = provision_org(db, clerk_org)
        user = provision_user(db, org, claims, role, org_created=created)
        if created:
            from app import emails

            emails.send_welcome(db, org, user.email)
        ctx = AuthContext(org.id, user.id, user.role, user.email, "clerk")
    else:
        if settings.auth_mode != "header":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bearer token required")
        if not x_org_id:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-Org-Id header required")
        try:
            org_id = uuid.UUID(x_org_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-Org-Id must be a UUID") from exc
        if db.scalar(select(Organization.id).where(Organization.id == org_id)) is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown organization")
        role = request.headers.get("X-Role", "owner")  # dev/e2e: pretend a role
        ctx = AuthContext(org_id, None, role if role in ROLE_RANK else "owner", None, "header")

    if request.method not in READ_METHODS and ctx.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "viewers are read-only")
    request.state.auth = ctx
    return ctx


Ctx = Annotated[AuthContext, Depends(get_auth)]


def get_org_id(ctx: Ctx) -> uuid.UUID:
    return ctx.org_id


OrgId = Annotated[uuid.UUID, Depends(get_org_id)]
