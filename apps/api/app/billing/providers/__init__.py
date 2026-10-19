"""Payment providers behind one interface. `active()` takes new checkouts; every configured
provider keeps receiving webhooks so a switch never strands existing subscribers."""

from __future__ import annotations

from fastapi import HTTPException, status

from app.billing.providers.base import BillingUpdate, Provider
from app.billing.providers.lemonsqueezy import LemonSqueezy
from app.billing.providers.paddle import Paddle
from app.billing.providers.stripe import Stripe
from app.config import settings

PROVIDERS: dict[str, Provider] = {p.name: p for p in (LemonSqueezy(), Paddle(), Stripe())}


def get(name: str) -> Provider:
    try:
        return PROVIDERS[name]
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown provider {name!r}") from exc


def active() -> Provider:
    name = settings.active_billing_provider
    if not name:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "billing is not configured")
    return PROVIDERS[name]


def for_org(org_provider: str | None, has_stripe: bool) -> Provider:
    """The provider that holds this org's current subscription (for the portal)."""
    if org_provider in PROVIDERS:
        return PROVIDERS[org_provider]
    if has_stripe:
        return PROVIDERS["stripe"]
    return active()


__all__ = ["PROVIDERS", "BillingUpdate", "Provider", "active", "for_org", "get"]
