"""Lemon Squeezy + Paddle: checkout/portal via the active provider, signed webhooks, dedupe,
status mapping, org lookup, audit. Provider HTTP goes through base._http_client (MockTransport)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import pytest
from sqlalchemy import select

from app.billing import plans
from app.billing.providers import base, paddle
from app.config import settings
from app.models import AuditLog, BillingEvent, Organization
from app.security import production_guard

LS_SECRET = "ls_whsec"
PD_SECRET = "pdl_ntfset_test"


@pytest.fixture
def lemonsqueezy(monkeypatch):
    for k, v in {
        "lemonsqueezy_api_key": "ls_key",
        "lemonsqueezy_store_id": "4242",
        "lemonsqueezy_webhook_secret": LS_SECRET,
        "lemonsqueezy_variant_starter": "101",
        "lemonsqueezy_variant_growth": "102",
        "lemonsqueezy_variant_scale": "103",
        "lemonsqueezy_beta_discount_code": "BETA50",
    }.items():
        monkeypatch.setattr(settings, k, v)


@pytest.fixture
def paddle_on(monkeypatch):
    for k, v in {
        "billing_provider": "paddle",
        "paddle_api_key": "pdl_key",
        "paddle_webhook_secret": PD_SECRET,
        "paddle_price_starter": "pri_s",
        "paddle_price_growth": "pri_g",
        "paddle_price_scale": "pri_x",
        "paddle_beta_discount_id": "dsc_beta",
    }.items():
        monkeypatch.setattr(settings, k, v)


@pytest.fixture
def http(monkeypatch):
    """Records provider requests and answers from `routes` (method, path suffix) -> json."""
    calls: list[httpx.Request] = []
    routes: dict[tuple[str, str], dict] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        for (method, suffix), body in routes.items():
            if req.method == method and req.url.path.endswith(suffix):
                return httpx.Response(200, json=body)
        return httpx.Response(500, json={"error": "secret detail"})

    monkeypatch.setattr(
        base, "_http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    return calls, routes


def _ls_post(client, body: dict, secret: str = LS_SECRET):
    raw = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(
        "/webhooks/lemonsqueezy",
        content=raw,
        headers={"X-Signature": sig, "Content-Type": "application/json"},
    )


def _pd_post(client, body: dict, ts: int | None = None, secret: str = PD_SECRET):
    raw = json.dumps(body).encode()
    ts = ts or int(time.time())
    h1 = hmac.new(secret.encode(), f"{ts}:".encode() + raw, hashlib.sha256).hexdigest()
    return client.post(
        "/webhooks/paddle",
        content=raw,
        headers={"Paddle-Signature": f"ts={ts};h1={h1}", "Content-Type": "application/json"},
    )


def _ls_sub(org, event: str, status: str, variant: int = 102, sub_id: int = 77, at: str = "t1"):
    return {
        "meta": {"event_name": event, "custom_data": {"org_id": str(org.id), "plan": "growth"}},
        "data": {
            "type": "subscriptions",
            "id": str(sub_id),
            "attributes": {
                "customer_id": 555,
                "variant_id": variant,
                "status": status,
                "user_email": "owner@shop.co",
                "updated_at": at,
            },
        },
    }


# --------------------------------------------------------------------------- provider choice
def test_active_provider_order_and_override(monkeypatch, lemonsqueezy) -> None:
    assert settings.active_billing_provider == "lemonsqueezy" and settings.billing_enabled
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test")
    assert settings.active_billing_provider == "lemonsqueezy"  # MoR first
    monkeypatch.setattr(settings, "billing_provider", "stripe")
    assert settings.active_billing_provider == "stripe"
    monkeypatch.setattr(settings, "billing_provider", "paddle")  # chosen but no keys
    assert settings.active_billing_provider == "" and not settings.billing_enabled


def test_production_guard_needs_webhook_secrets(monkeypatch, lemonsqueezy) -> None:
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "lemonsqueezy_webhook_secret", "")
    monkeypatch.setattr(settings, "paddle_api_key", "pdl")
    probs = " ".join(production_guard())
    assert "LEMONSQUEEZY_WEBHOOK_SECRET" in probs and "PADDLE_WEBHOOK_SECRET" in probs


# --------------------------------------------------------------------------- Lemon Squeezy
def test_ls_checkout_carries_org_plan_and_beta_code(
    client, db, org, headers, lemonsqueezy, http
) -> None:
    calls, routes = http
    routes[("POST", "/v1/checkouts")] = {
        "data": {"attributes": {"url": "https://shop.lemonsqueezy.com/c/abc"}}
    }
    org.is_beta = True
    db.flush()
    r = client.post("/billing/checkout", json={"plan": "growth"}, headers=headers)
    assert r.status_code == 200 and r.json()["url"].endswith("/c/abc")
    sent = json.loads(calls[0].content)["data"]
    assert calls[0].headers["authorization"] == "Bearer ls_key"
    assert sent["relationships"]["variant"]["data"]["id"] == "102"
    assert sent["relationships"]["store"]["data"]["id"] == "4242"
    assert sent["attributes"]["checkout_data"]["custom"] == {
        "org_id": str(org.id),
        "plan": "growth",
    }
    assert sent["attributes"]["checkout_data"]["discount_code"] == "BETA50"
    b = client.get("/billing", headers=headers).json()
    assert b["billing_provider"] == "lemonsqueezy" and b["billing_enabled"] is True


def test_ls_checkout_errors_hide_provider_body(client, headers, lemonsqueezy, http) -> None:
    r = client.post("/billing/checkout", json={"plan": "growth"}, headers=headers)
    assert r.status_code == 502 and "secret detail" not in r.text


def test_viewer_cannot_start_checkout(client, headers, lemonsqueezy, http) -> None:
    r = client.post(
        "/billing/checkout", json={"plan": "growth"}, headers={**headers, "X-Role": "viewer"}
    )
    assert r.status_code == 403


def test_ls_webhook_lifecycle(client, db, org, lemonsqueezy) -> None:
    assert (
        _ls_post(client, _ls_sub(org, "subscription_created", "active")).json()["result"]
        == "applied"
    )
    db.refresh(org)
    assert (org.plan, org.plan_status, org.billing_provider) == ("growth", "active", "lemonsqueezy")
    assert (org.billing_customer_id, org.billing_subscription_id) == ("555", "77")
    assert org.billing_email == "owner@shop.co"
    assert plans.effective_plan(org).key == "growth"

    # replay is a no-op
    assert (
        _ls_post(client, _ls_sub(org, "subscription_created", "active")).json()["result"]
        == "duplicate"
    )

    # upgrade via variant id (custom plan says growth, variant wins)
    _ls_post(client, _ls_sub(org, "subscription_updated", "active", variant=103, at="t2"))
    db.refresh(org)
    assert org.plan == "scale"

    # payment failed (invoice object, found by subscription id even without custom data)
    inv = {
        "meta": {"event_name": "subscription_payment_failed"},
        "data": {
            "type": "subscription-invoices",
            "id": "9",
            "attributes": {"subscription_id": 77, "customer_id": 555, "updated_at": "t3"},
        },
    }
    _ls_post(client, inv)
    db.refresh(org)
    assert org.plan_status == "past_due" and plans.effective_plan(org).key == "scale"

    # cancelled = runs to period end; expired = locked
    _ls_post(client, _ls_sub(org, "subscription_cancelled", "cancelled", variant=103, at="t4"))
    db.refresh(org)
    assert org.plan_status == "active"
    _ls_post(client, _ls_sub(org, "subscription_expired", "expired", variant=103, at="t5"))
    db.refresh(org)
    assert org.plan_status == "canceled" and org.billing_subscription_id is None
    assert plans.effective_plan(org).key == "locked"

    actions = db.scalars(select(AuditLog.action).where(AuditLog.org_id == org.id)).all()
    assert "billing.lemonsqueezy.subscription_created" in actions
    assert (
        db.scalar(select(BillingEvent).where(BillingEvent.provider == "lemonsqueezy")) is not None
    )


def test_ls_old_subscription_ending_does_not_touch_new_one(client, db, org, lemonsqueezy) -> None:
    _ls_post(client, _ls_sub(org, "subscription_created", "active", sub_id=78))
    _ls_post(client, _ls_sub(org, "subscription_expired", "expired", sub_id=11, at="old"))
    db.refresh(org)
    assert (org.plan_status, org.billing_subscription_id) == ("active", "78")


def test_ls_webhook_rejects_bad_signature_and_ignores_other_events(
    client, org, lemonsqueezy
) -> None:
    assert (
        _ls_post(client, _ls_sub(org, "subscription_created", "active"), secret="wrong").status_code
        == 400
    )
    r = client.post("/webhooks/lemonsqueezy", content=b"{}")
    assert r.status_code == 400
    assert (
        _ls_post(client, {"meta": {"event_name": "order_created"}, "data": {}}).json()["result"]
        == "ignored"
    )


def test_ls_portal_uses_subscription_portal_url(
    client, db, org, headers, lemonsqueezy, http
) -> None:
    calls, routes = http
    org.billing_provider, org.billing_subscription_id = "lemonsqueezy", "77"
    db.flush()
    routes[("GET", "/v1/subscriptions/77")] = {
        "data": {
            "attributes": {"urls": {"customer_portal": "https://shop.lemonsqueezy.com/billing?x=1"}}
        }
    }
    r = client.post("/billing/portal", headers=headers)
    assert r.status_code == 200 and "billing?x=1" in r.json()["url"]
    assert client.get("/billing", headers=headers).json()["has_subscription"] is True


# --------------------------------------------------------------------------- Paddle
def test_paddle_checkout_and_portal(client, db, org, headers, paddle_on, http) -> None:
    calls, routes = http
    routes[("POST", "/transactions")] = {
        "data": {
            "id": "txn_1",
            "checkout": {"url": "https://app.stockcast.app/billing/pay?_ptxn=txn_1"},
        }
    }
    org.is_beta = True
    db.flush()
    r = client.post("/billing/checkout", json={"plan": "starter"}, headers=headers)
    assert r.status_code == 200 and r.json()["url"].endswith("_ptxn=txn_1")
    sent = json.loads(calls[0].content)
    assert str(calls[0].url).startswith("https://sandbox-api.paddle.com/")
    assert sent["items"] == [{"price_id": "pri_s", "quantity": 1}]
    assert sent["custom_data"] == {"org_id": str(org.id), "plan": "starter"}
    assert sent["discount_id"] == "dsc_beta"

    org.billing_provider, org.billing_customer_id, org.billing_subscription_id = (
        "paddle",
        "ctm_1",
        "sub_1",
    )
    db.flush()
    routes[("POST", "/customers/ctm_1/portal-sessions")] = {
        "data": {"urls": {"general": {"overview": "https://customer-portal.paddle.com/x"}}}
    }
    r = client.post("/billing/portal", headers=headers)
    assert r.json()["url"] == "https://customer-portal.paddle.com/x"
    assert json.loads(calls[-1].content) == {"subscription_ids": ["sub_1"]}


def test_paddle_production_host(monkeypatch, paddle_on) -> None:
    monkeypatch.setattr(settings, "paddle_environment", "production")
    assert paddle.api_base() == "https://api.paddle.com"


def _pd_sub(org, event_id: str, etype: str, status: str, price: str = "pri_g"):
    return {
        "event_id": event_id,
        "event_type": etype,
        "data": {
            "id": "sub_1",
            "status": status,
            "customer_id": "ctm_1",
            "custom_data": {"org_id": str(org.id), "plan": "growth"},
            "items": [{"price": {"id": price}}],
        },
    }


def test_paddle_webhook_lifecycle(client, db, org, paddle_on) -> None:
    assert (
        _pd_post(client, _pd_sub(org, "evt_1", "subscription.created", "active")).json()["result"]
        == "applied"
    )
    db.refresh(org)
    assert (org.plan, org.plan_status, org.billing_provider, org.billing_customer_id) == (
        "growth",
        "active",
        "paddle",
        "ctm_1",
    )
    assert (
        _pd_post(client, _pd_sub(org, "evt_1", "subscription.created", "active")).json()["result"]
        == "duplicate"
    )

    failed = {
        "event_id": "evt_2",
        "event_type": "transaction.payment_failed",
        "data": {"id": "txn_9", "subscription_id": "sub_1", "customer_id": "ctm_1"},
    }
    _pd_post(client, failed)
    db.refresh(org)
    assert org.plan_status == "past_due"

    _pd_post(client, _pd_sub(org, "evt_3", "subscription.canceled", "canceled"))
    db.refresh(org)
    assert org.plan_status == "canceled" and plans.effective_plan(org).key == "locked"

    other = {"event_id": "evt_4", "event_type": "customer.updated", "data": {}}
    assert _pd_post(client, other).json()["result"] == "ignored"


def test_paddle_webhook_signature_and_replay_window(client, org, paddle_on) -> None:
    body = _pd_sub(org, "evt_9", "subscription.created", "active")
    assert _pd_post(client, body, secret="wrong").status_code == 400
    assert _pd_post(client, body, ts=int(time.time()) - 3600).status_code == 400
    assert client.post("/webhooks/paddle", content=b"{}").status_code == 400


def test_webhook_without_secret_is_503(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "lemonsqueezy_webhook_secret", "")
    assert client.post("/webhooks/lemonsqueezy", content=b"{}").status_code == 503


def test_unknown_org_is_ignored(client, db, lemonsqueezy) -> None:
    body = {
        "meta": {"event_name": "subscription_created", "custom_data": {"org_id": "not-a-uuid"}},
        "data": {
            "type": "subscriptions",
            "id": "1",
            "attributes": {"status": "active", "customer_id": 1},
        },
    }
    assert _ls_post(client, body).json()["result"] == "ignored"


def test_checkout_without_any_provider_is_503(client, headers) -> None:
    assert (
        client.post("/billing/checkout", json={"plan": "growth"}, headers=headers).status_code
        == 503
    )


def test_missing_price_is_503(client, headers, monkeypatch, lemonsqueezy) -> None:
    monkeypatch.setattr(settings, "lemonsqueezy_variant_scale", "")
    r = client.post("/billing/checkout", json={"plan": "scale"}, headers=headers)
    assert r.status_code == 503 and "scale" in r.json()["detail"]


def test_stripe_org_portal_still_goes_to_stripe(
    client, db, org, headers, monkeypatch, lemonsqueezy
) -> None:
    from app.billing import stripe_service

    org.stripe_customer_id, org.stripe_subscription_id = "cus_1", "sub_s"
    db.flush()
    monkeypatch.setattr(
        stripe_service, "create_portal", lambda db, o, e: "https://billing.stripe.com/p"
    )
    assert (
        client.post("/billing/portal", headers=headers).json()["url"]
        == "https://billing.stripe.com/p"
    )


def test_organization_model_has_billing_columns(db, org) -> None:
    assert db.scalar(select(Organization.billing_provider).where(Organization.id == org.id)) is None
