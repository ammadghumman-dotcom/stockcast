"""Lemon Squeezy (merchant of record; bank payouts to Pakistan).

- Checkout: POST /v1/checkouts with the plan's variant, `checkout_data.custom = {org_id, plan}`
  (echoed back in every webhook's `meta.custom_data`), the beta discount code if any.
- Portal: the signed `urls.customer_portal` of the subscription (valid 24 h, fetched on demand).
- Webhooks: `X-Signature` = hex HMAC-SHA256 of the raw body with the webhook secret.
  Subscription status `cancelled` still runs to the period end, so it stays active here;
  `expired` is the real end.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.billing.providers import base
from app.billing.providers.base import BillingUpdate
from app.config import settings
from app.models import Organization

log = logging.getLogger(__name__)
API = "https://api.lemonsqueezy.com/v1"
JSONAPI = "application/vnd.api+json"

STATUS = {
    "on_trial": base.TRIALING,
    "active": base.ACTIVE,
    "cancelled": base.ACTIVE,  # cancelled = won't renew; paid until ends_at -> then `expired`
    "past_due": base.PAST_DUE,
    "paused": base.PAUSED,
    "unpaid": base.UNPAID,
    "expired": base.CANCELED,
}
PAYMENT_STATUS = {
    "subscription_payment_failed": base.PAST_DUE,
    "subscription_payment_success": base.ACTIVE,
    "subscription_payment_recovered": base.ACTIVE,
}


def _variants() -> dict[str, str]:
    return {
        "starter": settings.lemonsqueezy_variant_starter,
        "growth": settings.lemonsqueezy_variant_growth,
        "scale": settings.lemonsqueezy_variant_scale,
    }


def _headers() -> dict[str, str]:
    return {
        "Accept": JSONAPI,
        "Content-Type": JSONAPI,
        "Authorization": f"Bearer {settings.lemonsqueezy_api_key}",
    }


class LemonSqueezy:
    name = "lemonsqueezy"

    def configured(self) -> bool:
        return bool(settings.lemonsqueezy_api_key and settings.lemonsqueezy_store_id)

    def _require(self) -> None:
        if not self.configured():
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "billing is not configured")

    def checkout_url(self, db: Session, org: Organization, plan: str, email: str | None) -> str:
        self._require()
        variant = base.require_plan(plan, _variants(), "Lemon Squeezy")
        checkout_data: dict[str, Any] = {"custom": {"org_id": str(org.id), "plan": plan}}
        if email or org.billing_email:
            checkout_data["email"] = email or org.billing_email
        if org.is_beta and settings.lemonsqueezy_beta_discount_code:
            checkout_data["discount_code"] = settings.lemonsqueezy_beta_discount_code
        body = {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "checkout_data": checkout_data,
                    "product_options": {
                        "redirect_url": f"{settings.web_base_url}/settings?billing=success"
                    },
                },
                "relationships": {
                    "store": {"data": {"type": "stores", "id": settings.lemonsqueezy_store_id}},
                    "variant": {"data": {"type": "variants", "id": variant}},
                },
            }
        }
        with base._http_client() as http:
            resp = http.post(f"{API}/checkouts", headers=_headers(), json=body)
        if resp.status_code >= 300:
            log.warning("lemonsqueezy checkout failed: %s %s", resp.status_code, resp.text[:300])
            raise base.provider_error("Lemon Squeezy", resp)
        url = (((resp.json().get("data") or {}).get("attributes")) or {}).get("url")
        if not url:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Lemon Squeezy returned no url")
        return str(url)

    def portal_url(self, db: Session, org: Organization) -> str:
        self._require()
        if org.billing_provider != self.name or not (
            org.billing_subscription_id or org.billing_customer_id
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no Lemon Squeezy subscription")
        path = (
            f"subscriptions/{org.billing_subscription_id}"
            if org.billing_subscription_id
            else f"customers/{org.billing_customer_id}"
        )
        with base._http_client() as http:
            resp = http.get(f"{API}/{path}", headers=_headers())
        if resp.status_code >= 300:
            raise base.provider_error("Lemon Squeezy", resp)
        attrs = (resp.json().get("data") or {}).get("attributes") or {}
        url = (attrs.get("urls") or {}).get("customer_portal")
        if not url:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Lemon Squeezy returned no portal")
        return str(url)

    def parse_webhook(self, payload: bytes, headers: Mapping[str, str]) -> BillingUpdate | None:
        secret = settings.lemonsqueezy_webhook_secret
        if not secret:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "webhook secret not set")
        sig = headers.get("x-signature")
        if not sig or not base.verify_hex_hmac(secret, payload, sig):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid signature")
        body = json.loads(payload)
        meta = body.get("meta") or {}
        event = str(meta.get("event_name") or headers.get("x-event-name") or "")
        data = body.get("data") or {}
        attrs = data.get("attributes") or {}
        custom = meta.get("custom_data") or {}
        if not event.startswith("subscription_"):
            return None
        stamp = attrs.get("updated_at") or attrs.get("created_at") or ""
        upd = BillingUpdate(
            event_id=f"{event}:{data.get('type')}:{data.get('id')}:{stamp}",
            type=event,
            org_ref=custom.get("org_id"),
            customer_id=_s(attrs.get("customer_id")),
            email=attrs.get("user_email"),
        )
        if data.get("type") == "subscriptions":
            upd.subscription_id = _s(data.get("id"))
            upd.status = STATUS.get(str(attrs.get("status")))
            upd.plan = base.plan_for_ref(_s(attrs.get("variant_id")), _variants())
        else:  # subscription-invoices (payment_* events)
            upd.subscription_id = _s(attrs.get("subscription_id"))
            upd.status = PAYMENT_STATUS.get(event)
        if upd.plan is None and custom.get("plan"):
            upd.plan = custom["plan"]
        return upd


def _s(v: Any) -> str | None:
    return None if v is None else str(v)
