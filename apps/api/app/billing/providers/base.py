"""What every payment provider gives the rest of the app.

A provider turns its own webhook payloads into `BillingUpdate`s; `app.billing.events.apply`
is the single place that changes `org.plan` / `plan_status`, for every provider alike.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.billing.plans import PLANS
from app.models import Organization

# Normalised subscription statuses (same vocabulary Stripe uses, so plans.ACTIVE_STATUSES works)
ACTIVE, TRIALING, PAST_DUE, PAUSED, UNPAID, CANCELED = (
    "active",
    "trialing",
    "past_due",
    "paused",
    "unpaid",
    "canceled",
)


@dataclass
class BillingUpdate:
    """One webhook delivery, provider-neutral."""

    event_id: str  # dedupe key, unique per provider
    type: str  # provider's event name, for the audit log
    org_ref: str | None = None  # our org id from checkout custom data
    customer_id: str | None = None
    subscription_id: str | None = None
    plan: str | None = None  # starter | growth | scale, if the event says
    status: str | None = None  # normalised status, None = no change
    email: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


class Provider(Protocol):
    name: str

    def configured(self) -> bool: ...
    def checkout_url(self, db: Session, org: Organization, plan: str, email: str | None) -> str: ...
    def portal_url(self, db: Session, org: Organization) -> str: ...
    def parse_webhook(self, payload: bytes, headers: Mapping[str, str]) -> BillingUpdate | None: ...


def _http_client() -> httpx.Client:
    """Injection seam for tests (httpx.MockTransport)."""
    return httpx.Client(timeout=20)


def plan_for_ref(ref: str | None, refs: Mapping[str, str]) -> str | None:
    """Map a provider price/variant id back to our plan key."""
    if not ref:
        return None
    for key, value in refs.items():
        if value and str(value) == str(ref):
            return key
    return None


def require_plan(plan: str, refs: Mapping[str, str], provider: str) -> str:
    if plan not in PLANS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown plan {plan!r}")
    ref = refs.get(plan, "")
    if not ref:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"no {provider} price for {plan}")
    return ref


def verify_hex_hmac(secret: str, message: bytes, signature: str) -> bool:
    expected = hmac.new(secret.encode(), message, "sha256").hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def provider_error(provider: str, resp: httpx.Response) -> HTTPException:
    # Never echo the provider body to users; it may include ids or keys in error details
    return HTTPException(
        status.HTTP_502_BAD_GATEWAY, f"{provider} returned HTTP {resp.status_code}; try again"
    )
