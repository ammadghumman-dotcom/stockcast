"""Stockcast as an embedded Shopify app: workspace-per-shop, token-exchange install, Billing API.

- org_for_shop: the workspace a shop's admin users land in. A shop connected earlier through the
  standalone OAuth flow keeps its workspace; otherwise one is created on first open (trial).
- install: exchange the App Bridge ID token for an expiring offline token, store it on the shop's
  channel, register webhooks and start the 2-year backfill. Idempotent per open.
- subscribe / apply_subscription_update: Shopify Billing API for Shopify-installed workspaces.
  `app_subscriptions/update` is what changes org.plan for them (as Stripe webhooks do for others).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import analytics, crypto
from app.billing.plans import PLANS, assert_can_add_channel
from app.config import settings
from app.ingest.base import ConnectorError
from app.ingest.shopify import oauth
from app.ingest.shopify.client import ShopifyGraphQL
from app.ingest.shopify.connector import ShopifyConnector, fresh_credentials
from app.models import Channel, ChannelType, Organization
from app.services import audit

log = logging.getLogger(__name__)

BETA_DISCOUNT_PCT = 0.5
BETA_DISCOUNT_MONTHS = 6
SUBSCRIPTION_PREFIX = "Stockcast "  # subscription name = "Stockcast Growth" -> plan "growth"


def org_for_shop(db: Session, shop: str) -> tuple[Organization, bool]:
    org = db.scalar(select(Organization).where(Organization.shopify_shop == shop))
    if org:
        return org, False
    channel = db.scalar(
        select(Channel)
        .where(Channel.type == ChannelType.shopify, Channel.external_shop_id == shop)
        .order_by(Channel.created_at)
    )
    if channel is not None:
        org = db.get(Organization, channel.org_id)
        assert org is not None
        if org.shopify_shop is None:
            org.shopify_shop = shop
            db.commit()
        return org, False
    from app.deps import create_org

    handle = shop.removesuffix(".myshopify.com")
    org = create_org(db, name=handle.replace("-", " ").title(), slug_base=handle, shopify_shop=shop)
    return org, True


def shop_channel(db: Session, org: Organization, shop: str) -> Channel | None:
    return db.scalar(
        select(Channel).where(
            Channel.org_id == org.id,
            Channel.type == ChannelType.shopify,
            Channel.external_shop_id == shop,
        )
    )


def install(db: Session, org: Organization, shop: str, id_token: str) -> tuple[Channel, bool]:
    """Ensure the shop's channel has a working token. Returns (channel, newly_installed)."""
    channel = shop_channel(db, org, shop)
    if channel is not None and channel.is_active and channel.credentials_encrypted:
        return channel, False
    creds = oauth.token_exchange(shop, id_token)
    if channel is None:
        assert_can_add_channel(db, org.id)
        channel = Channel(
            org_id=org.id,
            name=shop.removesuffix(".myshopify.com"),
            type=ChannelType.shopify,
            external_shop_id=shop,
        )
        db.add(channel)
    channel.credentials_encrypted = crypto.encrypt(json.dumps(creds))
    channel.is_active = True
    db.commit()
    db.refresh(channel)
    try:
        ShopifyConnector(channel).register_webhooks()
        channel.webhooks_registered = True
        db.commit()
    except ConnectorError:
        log.warning("webhook registration failed for %s; retried on next open", shop)
    from app.ingest.tasks import enqueue_sync

    enqueue_sync(db, channel, trigger="install", full=True)
    analytics.track(db, org.id, "channel_connected", props={"type": "shopify", "embedded": True})
    return channel, True


# ---- Billing API ------------------------------------------------------------------------------
SUBSCRIBE = """
mutation Subscribe($name: String!, $returnUrl: URL!, $test: Boolean, $trialDays: Int,
                   $lineItems: [AppSubscriptionLineItemInput!]!) {
  appSubscriptionCreate(name: $name, returnUrl: $returnUrl, test: $test, trialDays: $trialDays,
                        lineItems: $lineItems) {
    userErrors { field message }
    appSubscription { id }
    confirmationUrl
  }
}
"""
SHOP_PLAN = "query { shop { plan { partnerDevelopment } } }"


def subscription_name(plan_key: str) -> str:
    return SUBSCRIPTION_PREFIX + PLANS[plan_key].name


def plan_from_name(name: str) -> str | None:
    for key, plan in PLANS.items():
        if (
            name.strip().lower() == subscription_name(key).lower()
            or name.strip().lower() == plan.name.lower()
        ):
            return key
    return None


def line_items(plan_key: str, *, beta: bool) -> list[dict[str, Any]]:
    details: dict[str, Any] = {
        "price": {"amount": PLANS[plan_key].price_usd, "currencyCode": "USD"},
        "interval": "EVERY_30_DAYS",
    }
    if beta:
        details["discount"] = {
            "value": {"percentage": BETA_DISCOUNT_PCT},
            "durationLimitInIntervals": BETA_DISCOUNT_MONTHS,
        }
    return [{"plan": {"appRecurringPricingDetails": details}}]


def return_url(shop: str) -> str:
    store = shop.removesuffix(".myshopify.com")
    return (
        f"https://admin.shopify.com/store/{store}/apps/{settings.shopify_app_handle}?billing=done"
    )


def _gql(db: Session, channel: Channel) -> ShopifyGraphQL:
    creds = fresh_credentials(channel)
    db.commit()  # persist a refreshed token
    return ShopifyGraphQL(creds["shop"], creds["access_token"])


def subscribe(db: Session, org: Organization, channel: Channel, plan_key: str) -> str:
    """Create a pending subscription; the merchant approves it at the returned URL."""
    if plan_key not in PLANS:
        raise ValueError(f"unknown plan {plan_key}")
    gql = _gql(db, channel)
    dev_store = bool(
        ((gql.query(SHOP_PLAN).get("shop") or {}).get("plan") or {}).get("partnerDevelopment")
    )
    data = gql.query(
        SUBSCRIBE,
        {
            "name": subscription_name(plan_key),
            "returnUrl": return_url(channel.external_shop_id or ""),
            "test": dev_store or settings.shopify_billing_test,
            # remaining free trial carries over so subscribing early costs nothing extra
            "trialDays": _trial_days_left(org),
            "lineItems": line_items(plan_key, beta=org.is_beta),
        },
    )["appSubscriptionCreate"]
    if data["userErrors"]:
        raise ConnectorError(data["userErrors"][0]["message"])
    return str(data["confirmationUrl"])


def _trial_days_left(org: Organization) -> int:
    from datetime import UTC, datetime

    if org.plan != "trial" or org.trial_ends_at is None:
        return 0
    return max(0, (org.trial_ends_at - datetime.now(UTC)).days)


STATUS_MAP = {
    "ACTIVE": "active",
    "CANCELLED": "canceled",
    "EXPIRED": "canceled",
    "DECLINED": None,  # merchant said no to a new charge: keep whatever they had
    "PENDING": None,
    "FROZEN": "past_due",  # store paused/unpaid: keeps working, like Stripe dunning
}


def apply_subscription_update(db: Session, shop: str, sub: dict[str, Any]) -> bool:
    """Handle app_subscriptions/update. Returns True when the workspace's plan changed."""
    org = db.scalar(select(Organization).where(Organization.shopify_shop == shop))
    if org is None:
        return False
    sub_id = sub.get("admin_graphql_api_id")
    status = STATUS_MAP.get(str(sub.get("status", "")).upper())
    plan_key = plan_from_name(str(sub.get("name", "")))
    before = {"plan": org.plan, "plan_status": org.plan_status}
    if status == "active" and plan_key:
        org.plan, org.plan_status, org.shopify_subscription_id = plan_key, "active", sub_id
    elif status in ("canceled", "past_due") and sub_id and sub_id == org.shopify_subscription_id:
        org.plan_status = status
    else:
        return False
    audit.record(
        db,
        None,
        org_id=org.id,
        action="billing.shopify_subscription",
        entity="organization",
        entity_id=org.id,
        before=before,
        after={"plan": org.plan, "plan_status": org.plan_status, "subscription": sub_id},
        actor="shopify",
    )
    db.commit()
    return True
