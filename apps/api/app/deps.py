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

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
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
            leeway=10,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {exc}") from exc


def _clerk_fetch(path: str) -> dict | None:
    """Best-effort name lookup via the Clerk Backend API (needs CLERK_SECRET_KEY)."""
    if not settings.clerk_secret_key:
        return None
    try:
        r = httpx.get(
            f"https://api.clerk.com/v1{path}",
            headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            timeout=5,
        )
        return r.json() if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def provision_org(db: Session, clerk_org_id: str, name: str | None = None) -> Organization:
    org = db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if org:
        return org
    info = _clerk_fetch(f"/organizations/{clerk_org_id}")
    name = name or (info or {}).get("name") or f"Workspace {clerk_org_id[-6:]}"
    slug_base = (info or {}).get("slug") or clerk_org_id[-12:].lower()
    slug, n = slug_base, 1
    while db.scalar(select(Organization.id).where(Organization.slug == slug)):
        n += 1
        slug = f"{slug_base}-{n}"
    org = Organization(
        name=name,
        slug=slug,
        clerk_org_id=clerk_org_id,
        plan="trial",
        plan_status="trialing",
        trial_ends_at=datetime.now(UTC) + timedelta(days=settings.trial_days),
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


def provision_user(db: Session, org: Organization, claims: dict, role: str) -> User:
    sub = claims["sub"]
    user = db.scalar(select(User).where(User.org_id == org.id, User.external_auth_id == sub))
    if user:
        if user.role != role:
            user.role = role
            db.commit()
        return user
    email = claims.get("email")
    name = claims.get("name") or claims.get("first_name") or ""
    if not email or not name:
        info = _clerk_fetch(f"/users/{sub}") or {}
        addresses = info.get("email_addresses") or []
        primary = next(
            (e for e in addresses if e.get("id") == info.get("primary_email_address_id")), None
        )
        email = (
            email
            or (primary or {}).get("email_address")
            or (addresses[0].get("email_address") if addresses else None)
            or f"{sub}@clerk.local"
        )
        name = name or f"{info.get('first_name', '')} {info.get('last_name', '')}".strip() or email
    user = User(org_id=org.id, email=email, name=name, role=role, external_auth_id=sub)
    db.add(user)
    db.commit()
    return user


# --------------------------------------------------------------------------- dependency
def get_auth(
    request: Request,
    db: DB,
    authorization: Annotated[str | None, Header()] = None,
    x_org_id: Annotated[str | None, Header(alias="X-Org-Id")] = None,
) -> AuthContext:
    if settings.auth_mode == "clerk" or (authorization and authorization.startswith("Bearer ")):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bearer token required")
        claims = verify_clerk_token(authorization.removeprefix("Bearer ").strip())
        clerk_org = claims.get("org_id")
        if not clerk_org:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "select an organization first")
        role = CLERK_ROLE_MAP.get(claims.get("org_role", ""), "viewer")
        org = provision_org(db, clerk_org)
        user = provision_user(db, org, claims, role)
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
