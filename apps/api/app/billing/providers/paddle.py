"""Paddle Billing (merchant of record).

- Checkout: POST /transactions with the plan's price and `custom_data = {org_id, plan}`;
  Paddle returns `checkout.url` built from the account's *default payment link*, which must
  point at `{WEB_BASE_URL}/billing/pay` (that page loads Paddle.js and opens the checkout).
- Portal: POST /customers/{id}/portal-sessions -> `urls.general.overview`.
- Webhooks: `Paddle-Signature: ts=..;h1=..`, h1 = hex HMAC-SHA256 of "{ts}:{raw body}".
  Scheduled cancellations keep status `active` until Paddle sends `canceled`.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.billing.providers import base
from app.billing.providers.base import BillingUpdate
from app.config import settings
from app.models import Organization

log = logging.getLogger(__name__)
TOLERANCE_S = 300
STATUS = {
    "active": base.ACTIVE,
    "trialing": base.TRIALING,
    "past_due": base.PAST_DUE,
    "paused": base.PAUSED,
    "canceled": base.CANCELED,
}


def api_base() -> str:
    if settings.paddle_environment == "production":
        return "https://api.paddle.com"
    return "https://sandbox-api.paddle.com"


def _prices() -> dict[str, str]:
    return {
        "starter": settings.paddle_price_starter,
        "growth": settings.paddle_price_growth,
        "scale": settings.paddle_price_scale,
    }


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.paddle_api_key}",
        "Content-Type": "application/json",
    }


class Paddle:
    name = "paddle"

    def configured(self) -> bool:
        return bool(settings.paddle_api_key)

    def _require(self) -> None:
        if not self.configured():
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "billing is not configured")

    def checkout_url(self, db: Session, org: Organization, plan: str, email: str | None) -> str:
        self._require()
        price = base.require_plan(plan, _prices(), "Paddle")
        body: dict[str, Any] = {
            "items": [{"price_id": price, "quantity": 1}],
            "custom_data": {"org_id": str(org.id), "plan": plan},
        }
        if org.billing_provider == self.name and org.billing_customer_id:
            body["customer_id"] = org.billing_customer_id
        if org.is_beta and settings.paddle_beta_discount_id:
            body["discount_id"] = settings.paddle_beta_discount_id
        with base._http_client() as http:
            resp = http.post(f"{api_base()}/transactions", headers=_headers(), json=body)
        if resp.status_code >= 300:
            log.warning("paddle transaction failed: %s %s", resp.status_code, resp.text[:300])
            raise base.provider_error("Paddle", resp)
        url = ((resp.json().get("data") or {}).get("checkout") or {}).get("url")
        if not url:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "Paddle returned no checkout url (set a default payment link in Paddle)",
            )
        return str(url)

    def portal_url(self, db: Session, org: Organization) -> str:
        self._require()
        if org.billing_provider != self.name or not org.billing_customer_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no Paddle subscription")
        body = (
            {"subscription_ids": [org.billing_subscription_id]}
            if org.billing_subscription_id
            else {}
        )
        with base._http_client() as http:
            resp = http.post(
                f"{api_base()}/customers/{org.billing_customer_id}/portal-sessions",
                headers=_headers(),
                json=body,
            )
        if resp.status_code >= 300:
            raise base.provider_error("Paddle", resp)
        urls = (resp.json().get("data") or {}).get("urls") or {}
        url = (urls.get("general") or {}).get("overview")
        if not url:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Paddle returned no portal")
        return str(url)

    def parse_webhook(
        self, payload: bytes, headers: Mapping[str, str], now: float | None = None
    ) -> BillingUpdate | None:
        secret = settings.paddle_webhook_secret
        if not secret:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "webhook secret not set")
        parts: dict[str, list[str]] = {}
        for piece in (headers.get("paddle-signature") or "").split(";"):
            k, _, v = piece.partition("=")
            parts.setdefault(k.strip(), []).append(v.strip())
        ts = (parts.get("ts") or [""])[0]
        if not ts.isdigit() or abs((now or time.time()) - int(ts)) > TOLERANCE_S:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid signature")
        signed = ts.encode() + b":" + payload
        if not any(base.verify_hex_hmac(secret, signed, h) for h in parts.get("h1", [])):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid signature")
        body = json.loads(payload)
        etype = str(body.get("event_type") or "")
        data = body.get("data") or {}
        custom = data.get("custom_data") or {}
        upd = BillingUpdate(
            event_id=str(body.get("event_id") or ""),
            type=etype,
            org_ref=custom.get("org_id"),
            customer_id=data.get("customer_id"),
        )
        if etype.startswith("subscription."):
            upd.subscription_id = data.get("id")
            upd.status = STATUS.get(str(data.get("status")))
            for item in data.get("items") or []:
                upd.plan = base.plan_for_ref(((item.get("price") or {}).get("id")), _prices())
                if upd.plan:
                    break
        elif etype == "transaction.payment_failed" and data.get("subscription_id"):
            upd.subscription_id = data.get("subscription_id")
            upd.status = base.PAST_DUE
        else:
            return None
        if upd.plan is None and custom.get("plan"):
            upd.plan = custom["plan"]
        return upd
