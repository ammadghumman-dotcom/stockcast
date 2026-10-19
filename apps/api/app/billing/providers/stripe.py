"""Stripe adapter. Stripe keeps its own webhook route and handler (`stripe_service`); this only
lets the billing router pick it like any other provider."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.billing import stripe_service
from app.billing.providers.base import BillingUpdate
from app.config import settings
from app.models import Organization


class Stripe:
    name = "stripe"

    def configured(self) -> bool:
        return bool(settings.stripe_secret_key)

    def checkout_url(self, db: Session, org: Organization, plan: str, email: str | None) -> str:
        return stripe_service.create_checkout(db, org, plan, email)

    def portal_url(self, db: Session, org: Organization) -> str:
        return stripe_service.create_portal(db, org, org.billing_email)

    def parse_webhook(self, payload: bytes, headers: Mapping[str, str]) -> BillingUpdate | None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stripe uses /webhooks/stripe")
