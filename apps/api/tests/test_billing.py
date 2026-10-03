"""Plan limits, Stripe webhook idempotency, audit log."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.billing import plans
from app.config import settings
from app.models import AuditLog, Organization, PlanningRun, StripeEvent
from app.planning.engine import run_planning
from tests.conftest import PLANNING_AS_OF as AS_OF


def _product(sku: str) -> dict:
    return {"sku": sku, "name": sku, "type": "finished"}


# --------------------------------------------------------------------------- plan limits
def test_trial_has_growth_limits_and_billing_read(client: TestClient, headers: dict) -> None:
    b = client.get("/billing", headers=headers).json()
    assert b["plan"] == "trial" and b["effective_plan"] == "trial"
    assert b["limits"] == {"channels": 3, "skus": 5000}
    assert {p["key"]: p["price_usd"] for p in b["plans"]} == {
        "starter": 39,
        "growth": 99,
        "scale": 249,
    }


def test_starter_channel_limit(client: TestClient, db, org: Organization, headers: dict) -> None:
    org.plan, org.plan_status = "starter", "active"
    db.flush()
    assert (
        client.post("/channels", json={"name": "A", "type": "csv"}, headers=headers).status_code
        == 201
    )
    r = client.post("/channels", json={"name": "B", "type": "csv"}, headers=headers)
    assert r.status_code == 402
    assert "Starter plan allows 1" in r.json()["detail"]["detail"]
    # Shopify install is blocked before OAuth starts
    assert client.get("/shopify/install?shop=x.myshopify.com", headers=headers).status_code == 402
    # upgrade -> allowed
    org.plan = "growth"
    db.flush()
    assert (
        client.post("/channels", json={"name": "B", "type": "csv"}, headers=headers).status_code
        == 201
    )


def test_sku_limit_on_create_and_import(
    client: TestClient, db, org: Organization, headers: dict, monkeypatch
) -> None:
    monkeypatch.setitem(plans.PLANS, "starter", plans.Plan("starter", "Starter", 39, 1, 3))
    org.plan, org.plan_status = "starter", "active"
    db.flush()
    for i in range(3):
        assert client.post("/products", json=_product(f"S{i}"), headers=headers).status_code == 201
    assert client.post("/products", json=_product("S9"), headers=headers).status_code == 402

    # import: updating existing SKUs is fine, adding new ones over the cap is rejected atomically
    csv_ok = "sku,name\nS0,renamed\nS1,renamed\n"
    r = client.post(
        "/imports",
        files={"products": ("p.csv", io.BytesIO(csv_ok.encode()), "text/csv")},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    csv_over = "sku,name\nS0,x\nNEW1,x\nNEW2,x\n"
    r = client.post(
        "/imports",
        files={"products": ("p.csv", io.BytesIO(csv_over.encode()), "text/csv")},
        headers=headers,
    )
    assert r.status_code == 402
    assert len(client.get("/products", headers=headers).json()) == 3


def test_scale_is_unlimited_and_expired_trial_locks(db, org: Organization) -> None:
    org.plan, org.plan_status = "scale", "active"
    assert plans.limits_for(org) == {"channels": None, "skus": None}
    org.plan, org.plan_status = "trial", "trialing"
    org.trial_ends_at = datetime.now(UTC) - timedelta(days=1)
    assert plans.effective_plan(org) is plans.LOCKED
    org.plan, org.plan_status = "growth", "canceled"
    assert plans.effective_plan(org) is plans.LOCKED
    org.plan_status = "past_due"  # dunning: keep working
    assert plans.effective_plan(org).key == "growth"


def test_locked_org_cannot_add(client: TestClient, db, org: Organization, headers: dict) -> None:
    org.trial_ends_at = datetime.now(UTC) - timedelta(days=1)
    db.flush()
    r = client.post("/products", json=_product("X"), headers=headers)
    assert r.status_code == 402 and "trial has ended" in r.json()["detail"]["detail"]
    assert client.get("/products", headers=headers).status_code == 200  # reads still work


# --------------------------------------------------------------------------- Stripe webhooks
def _signed(payload: dict) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    ts = int(time.time())
    sig = hmac.new(
        settings.stripe_webhook_secret.encode(), f"{ts}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return body, {"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"}


def _event(etype: str, obj: dict, event_id: str | None = None) -> dict:
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex[:12]}",
        "object": "event",
        "type": etype,
        "api_version": "2024-06-20",
        "created": int(time.time()),
        "data": {"object": obj},
    }


def test_webhook_rejects_bad_signature(client: TestClient) -> None:
    body, h = _signed(_event("invoice.paid", {}))
    h["Stripe-Signature"] = "t=1,v1=deadbeef"
    assert client.post("/webhooks/stripe", content=body, headers=h).status_code == 400
    assert client.post("/webhooks/stripe", content=body).status_code == 400


def test_checkout_completed_activates_plan_and_is_idempotent(
    client: TestClient, db, org: Organization
) -> None:
    ev = _event(
        "checkout.session.completed",
        {
            "id": "cs_1",
            "object": "checkout.session",
            "client_reference_id": str(org.id),
            "customer": "cus_1",
            "subscription": "sub_1",
            "metadata": {"org_id": str(org.id), "plan": "growth"},
            "customer_details": {"email": "owner@acme.test"},
        },
        event_id="evt_once",
    )
    body, h = _signed(ev)
    r = client.post("/webhooks/stripe", content=body, headers=h)
    assert r.status_code == 200 and r.json()["result"] == "applied"
    db.refresh(org)
    assert (org.plan, org.plan_status, org.stripe_customer_id, org.stripe_subscription_id) == (
        "growth",
        "active",
        "cus_1",
        "sub_1",
    )
    assert org.billing_email == "owner@acme.test"

    # replayed delivery: acknowledged, not re-applied
    org.plan = "starter"
    db.flush()
    r = client.post("/webhooks/stripe", content=body, headers=h)
    assert r.status_code == 200 and r.json()["result"] == "duplicate"
    db.refresh(org)
    assert org.plan == "starter"
    assert db.scalar(select(StripeEvent).where(StripeEvent.event_id == "evt_once")) is not None

    # audit row written by the first delivery only
    rows = db.scalars(select(AuditLog).where(AuditLog.org_id == org.id)).all()
    assert [r.action for r in rows] == ["billing.checkout.session.completed"]
    assert rows[0].actor == "stripe" and rows[0].after["plan"] == "growth"


def test_subscription_lifecycle(client: TestClient, db, org: Organization) -> None:
    org.stripe_customer_id, org.plan, org.plan_status = "cus_9", "growth", "active"
    db.flush()

    def post(etype, obj):
        body, h = _signed(_event(etype, {"customer": "cus_9", **obj}))
        assert (
            client.post("/webhooks/stripe", content=body, headers=h).json()["result"] == "applied"
        )
        db.refresh(org)

    post(
        "customer.subscription.updated",
        {
            "id": "sub_9",
            "status": "active",
            "items": {"data": [{"price": {"id": settings.stripe_price_scale}}]},
        },
    )
    assert (org.plan, org.plan_status) == ("scale", "active")
    post("invoice.payment_failed", {"id": "in_1"})
    assert org.plan_status == "past_due"
    post("invoice.paid", {"id": "in_2"})
    assert org.plan_status == "active"
    post("customer.subscription.deleted", {"id": "sub_9", "status": "canceled"})
    assert org.plan_status == "canceled" and org.stripe_subscription_id is None
    assert plans.effective_plan(org) is plans.LOCKED


def test_unknown_event_type_is_recorded_and_ignored(client: TestClient, db) -> None:
    body, h = _signed(_event("charge.refunded", {"id": "ch_1"}, event_id="evt_ignored"))
    assert client.post("/webhooks/stripe", content=body, headers=h).json()["result"] == "ignored"
    assert client.post("/webhooks/stripe", content=body, headers=h).json()["result"] == "duplicate"


def test_checkout_requires_admin_and_config(client: TestClient, headers: dict) -> None:
    r = client.post(
        "/billing/checkout", json={"plan": "growth"}, headers={**headers, "X-Role": "viewer"}
    )
    assert r.status_code == 403
    r = client.post("/billing/checkout", json={"plan": "growth"}, headers=headers)
    assert r.status_code == 503  # no STRIPE_SECRET_KEY in tests
    assert (
        client.post("/billing/checkout", json={"plan": "gold"}, headers=headers).status_code == 422
    )


# --------------------------------------------------------------------------- audit log
def test_settings_and_po_changes_are_audited(client: TestClient, db, org, headers, candle_world):
    r = client.patch("/planning-settings", json={"service_level": 0.97}, headers=headers)
    assert r.status_code == 200, r.text
    row = db.scalar(
        select(AuditLog).where(AuditLog.org_id == org.id, AuditLog.action == "settings.update")
    )
    assert row is not None
    assert row.before == {"service_level": 0.95} and row.after == {"service_level": 0.97}

    run = PlanningRun(org_id=org.id)
    db.add(run)
    db.flush()
    run_planning(db, run, as_of=AS_OF)
    pos = client.post("/purchase-orders/from-recommendations", json={}, headers=headers)
    assert pos.status_code == 201, pos.text
    po_id = pos.json()[0]["id"]
    assert client.post(f"/purchase-orders/{po_id}/mark-sent", headers=headers).status_code == 200
    assert client.post(f"/purchase-orders/{po_id}/receive", headers=headers).status_code == 200
    actions = [
        a.action
        for a in db.scalars(
            select(AuditLog).where(AuditLog.entity_id == po_id).order_by(AuditLog.at)
        ).all()
    ]
    assert actions == ["po.create", "po.mark_sent", "po.receive"]
    sent = db.scalar(
        select(AuditLog).where(AuditLog.entity_id == po_id, AuditLog.action == "po.mark_sent")
    )
    assert sent.before["status"] == "draft" and sent.after["status"] == "sent"
