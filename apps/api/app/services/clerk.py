"""Thin Clerk Backend API client (organizations, invitations, memberships).

Clerk is the source of truth for who belongs to a workspace and with which role in
AUTH_MODE=clerk: every request re-reads the role from the session token. So Team changes made
in Stockcast are written to Clerk first; Stockcast's `users` rows mirror them.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings

BASE = "https://api.clerk.com/v1"

# Stockcast role <-> Clerk organization role. Clerk has no owner role by default; the owner is
# an org:admin whom Stockcast marks as owner (the workspace creator, or after a transfer).
TO_CLERK = {"owner": "org:admin", "admin": "org:admin", "viewer": "org:member"}


class ClerkError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def enabled() -> bool:
    return bool(settings.clerk_secret_key)


def _client() -> httpx.Client:  # seam for tests
    return httpx.Client(
        base_url=BASE,
        headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
        timeout=10,
    )


def _call(method: str, path: str, json: dict | None = None) -> dict[str, Any]:
    try:
        with _client() as c:
            r = c.request(method, path, json=json)
    except httpx.HTTPError as exc:
        raise ClerkError(502, f"Could not reach Clerk: {exc}") from exc
    if r.status_code >= 400:
        try:
            errs = r.json().get("errors") or []
            msg = "; ".join(e.get("long_message") or e.get("message", "") for e in errs)
        except ValueError:
            msg = r.text[:200]
        raise ClerkError(r.status_code, msg or f"Clerk returned {r.status_code}")
    return r.json() if r.content else {}


def get(path: str) -> dict[str, Any] | None:
    """Best-effort read: None when Clerk is not configured or the call fails."""
    if not enabled():
        return None
    try:
        return _call("GET", path)
    except ClerkError:
        return None


def invite(
    org_id: str, email: str, role: str, *, inviter: str | None, redirect_url: str | None
) -> dict[str, Any]:
    body: dict[str, Any] = {"email_address": email, "role": TO_CLERK[role]}
    if inviter:
        body["inviter_user_id"] = inviter
    if redirect_url:
        body["redirect_url"] = redirect_url
    return _call("POST", f"/organizations/{org_id}/invitations", body)


def revoke_invitation(org_id: str, invitation_id: str, *, requester: str | None) -> None:
    body = {"requesting_user_id": requester} if requester else {}
    _call("POST", f"/organizations/{org_id}/invitations/{invitation_id}/revoke", body)


def set_member_role(org_id: str, user_id: str, role: str) -> None:
    _call("PATCH", f"/organizations/{org_id}/memberships/{user_id}", {"role": TO_CLERK[role]})


def remove_member(org_id: str, user_id: str) -> None:
    _call("DELETE", f"/organizations/{org_id}/memberships/{user_id}")


def primary_email(user: dict[str, Any]) -> str | None:
    addresses = user.get("email_addresses") or []
    primary = next(
        (e for e in addresses if e.get("id") == user.get("primary_email_address_id")), None
    )
    return (primary or {}).get("email_address") or (
        addresses[0].get("email_address") if addresses else None
    )
