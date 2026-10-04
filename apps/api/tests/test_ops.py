"""Step 9: security middleware, readiness, production guard, Amazon webhook, ops alerts, logs."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app import crypto, observability, ops, security
from app.config import settings
from app.main import app
from app.models import Channel, ChannelType, ForecastRun, SyncRun


# --------------------------------------------------------------------------- transport security
def test_request_id_and_security_headers(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert len(r.headers["X-Request-Id"]) == 16
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Strict-Transport-Security" not in r.headers  # FORCE_HTTPS off in tests
    echoed = client.get("/health", headers={"X-Request-Id": "abc-123"})
    assert echoed.headers["X-Request-Id"] == "abc-123"


def test_https_redirect_and_hsts(db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "force_https", True)
    from app.db import get_db

    app.dependency_overrides[get_db] = lambda: db
    # rebuild middleware stack with the flag on
    https_app = app
    for mw in https_app.user_middleware:
        if mw.cls is security.HttpsMiddleware:
            mw.kwargs["enabled"] = True
    https_app.middleware_stack = None
    with TestClient(https_app, base_url="http://api.test") as c:
        r = c.get("/products", headers={"X-Forwarded-Proto": "http"}, follow_redirects=False)
        assert r.status_code == 308 and r.headers["location"].startswith(
            "https://api.test/products"
        )
        r = c.get("/health", headers={"X-Forwarded-Proto": "http"})  # health is exempt
        assert r.status_code == 200
        r = c.get("/health", headers={"X-Forwarded-Proto": "https"})
        assert r.headers["Strict-Transport-Security"].startswith("max-age=31536000")
    for mw in https_app.user_middleware:
        if mw.cls is security.HttpsMiddleware:
            mw.kwargs["enabled"] = False
    https_app.middleware_stack = None
    app.dependency_overrides.clear()


def test_cors_allowlist_only(client: TestClient) -> None:
    ok = client.options(
        "/products",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options(
        "/products",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in bad.headers


def test_production_guard_catches_dev_defaults(monkeypatch) -> None:
    assert security.production_guard() == []  # development: anything goes
    monkeypatch.setattr(settings, "env", "production")
    problems = security.production_guard()
    assert any("AUTH_MODE" in p for p in problems)
    assert any("CREDENTIALS_KEY" in p for p in problems)
    assert any("FORCE_HTTPS" in p for p in problems)
    monkeypatch.setattr(settings, "auth_mode", "clerk")
    monkeypatch.setattr(settings, "credentials_key", "x" * 32)
    monkeypatch.setattr(settings, "force_https", True)
    monkeypatch.setattr(settings, "cors_origins", "https://app.stockcast.app")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_x")
    assert security.production_guard() == []
    # billing is optional: no Stripe at all is fine, a key without a webhook secret is not
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    assert security.production_guard() == []
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_live_x")
    assert any("STRIPE_WEBHOOK_SECRET" in p for p in security.production_guard())


def test_trusted_hosts_always_include_railway_healthcheck(monkeypatch) -> None:
    monkeypatch.setattr(settings, "allowed_hosts", "api.example.com, ")
    assert security.trusted_hosts() == ["api.example.com", "healthcheck.railway.app"]
    monkeypatch.setattr(settings, "allowed_hosts", "healthcheck.railway.app,api.example.com")
    assert security.trusted_hosts().count("healthcheck.railway.app") == 1


def test_readiness_reports_dependencies(client: TestClient, monkeypatch) -> None:
    r = client.get("/health/ready")
    body = r.json() if r.status_code == 200 else r.json()["detail"]
    assert body["database"] == "ok"
    assert body["redis"] == "ok" or body["redis"].startswith("error")  # no redis in unit tests
    if body["redis"] != "ok":
        assert r.status_code == 503 and body["status"] == "degraded"


# --------------------------------------------------------------------------- Amazon webhook
def _amazon_channel(db, org, seller="A2SELLER"):
    ch = Channel(
        org_id=org.id,
        name="Amazon US",
        type=ChannelType.amazon,
        external_shop_id="ATVPDKIKX0DER",
        credentials_encrypted=crypto.encrypt(
            json.dumps(
                {"refresh_token": "r", "marketplace_id": "ATVPDKIKX0DER", "seller_id": seller}
            )
        ),
    )
    db.add(ch)
    db.flush()
    return ch


def _notification(nid: str, ntype: str = "ORDER_CHANGE") -> bytes:
    return json.dumps(
        {
            "NotificationVersion": "1.0",
            "NotificationType": ntype,
            "NotificationMetadata": {"NotificationId": nid, "SellerId": "A2SELLER"},
            "Payload": {"MarketplaceId": "ATVPDKIKX0DER", "OrderChangeNotification": {}},
        }
    ).encode()


def test_amazon_webhook_verifies_signature_and_dedupes(client, db, org, monkeypatch) -> None:
    monkeypatch.setattr(settings, "amazon_webhook_secret", "s3cret")
    ch = _amazon_channel(db, org)
    enqueued: list[uuid.UUID] = []
    monkeypatch.setattr(
        "app.routers.amazon_webhooks.enqueue_sync",
        lambda db, channel, **kw: enqueued.append(channel.id),
    )
    body = _notification("n-1")
    assert client.post("/webhooks/amazon", content=body).status_code == 401
    assert (
        client.post(
            "/webhooks/amazon", content=body, headers={"X-Amz-Webhook-Token": "wrong"}
        ).status_code
        == 401
    )
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    r = client.post("/webhooks/amazon", content=body, headers={"X-Amz-Webhook-Signature": sig})
    assert r.status_code == 200 and r.json()["result"] == "sync enqueued"
    assert enqueued == [ch.id]
    # replay -> deduped; token form also accepted
    r = client.post("/webhooks/amazon", content=body, headers={"X-Amz-Webhook-Token": "s3cret"})
    assert r.json()["result"] == "duplicate" and len(enqueued) == 1
    # unknown seller -> acknowledged, nothing enqueued
    other = _notification("n-2").replace(b"A2SELLER", b"ZZZ")
    r = client.post("/webhooks/amazon", content=other, headers={"X-Amz-Webhook-Token": "s3cret"})
    assert r.json()["result"] == "no matching channel"
    # non-sync topic
    r = client.post(
        "/webhooks/amazon",
        content=_notification("n-3", "REPORT_PROCESSING_FINISHED"),
        headers={"X-Amz-Webhook-Token": "s3cret"},
    )
    assert r.json()["result"] == "ignored" and len(enqueued) == 1


def test_amazon_webhook_without_secret_configured_rejects(client) -> None:
    r = client.post("/webhooks/amazon", content=b"{}", headers={"X-Amz-Webhook-Token": ""})
    assert r.status_code == 401


# --------------------------------------------------------------------------- ops alerts
@pytest.fixture
def alert_sink(monkeypatch):
    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        ops, "alert", lambda title, detail, level="error": sent.append((title, detail))
    )
    return sent


def _sync_runs(db, org, channel, statuses):
    for st in statuses:
        db.add(SyncRun(org_id=org.id, channel_id=channel.id, trigger="nightly", status=st))
    db.flush()


def test_sync_failure_rate_alert(db, org, alert_sink) -> None:
    ch = Channel(org_id=org.id, name="csv", type=ChannelType.csv)
    db.add(ch)
    db.flush()
    _sync_runs(db, org, ch, ["success"] * 19 + ["failed"])  # 5 % exactly: not above
    assert ops.run_checks(db) == []
    _sync_runs(db, org, ch, ["failed"])  # 2/21 = 9.5 %
    raised = ops.run_checks(db)
    assert [r["check"] for r in raised] == ["sync_failure_rate"]
    assert raised[0]["failed"] == 2 and raised[0]["total"] == 21
    assert alert_sink[0][0].startswith("Channel sync failure rate")


def test_forecast_duration_alert(db, org, alert_sink) -> None:
    now = datetime.now(UTC)
    fast = ForecastRun(
        org_id=org.id,
        status="success",
        started_at=now - timedelta(minutes=40),
        finished_at=now - timedelta(minutes=30),
    )
    slow = ForecastRun(
        org_id=org.id,
        status="success",
        started_at=now - timedelta(minutes=50),
        finished_at=now - timedelta(minutes=5),
    )
    stuck = ForecastRun(org_id=org.id, status="running", started_at=now - timedelta(minutes=45))
    db.add_all([fast, slow, stuck])
    db.flush()
    raised = ops.run_checks(db, now)
    assert {r["run_id"] for r in raised} == {str(slow.id), str(stuck.id)}
    assert all(r["check"] == "forecast_duration" for r in raised)


def test_alert_posts_to_webhook(monkeypatch) -> None:
    posted: list[dict] = []
    monkeypatch.setattr(settings, "alert_webhook_url", "https://hooks.example/x")
    monkeypatch.setattr(settings, "env", "staging")
    monkeypatch.setattr(
        httpx, "post", lambda url, json, timeout: posted.append(json) or httpx.Response(200)
    )
    observability.alert("Something broke", {"a": 1, "b": "two"}, level="warning")
    assert posted[0]["text"].startswith("[staging] Something broke\n• a: 1\n• b: two")


# --------------------------------------------------------------------------- logging
def test_json_logging_carries_request_id(capsys, monkeypatch) -> None:
    monkeypatch.setattr(observability, "_configured", False)
    monkeypatch.setattr(settings, "log_format", "json")
    observability.configure_logging()
    token = observability.request_id_var.set("req-42")
    try:
        logging.getLogger("stockcast.test").info("hello %s", "world")
    finally:
        observability.request_id_var.reset(token)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    rec = json.loads(line)
    assert rec["message"] == "hello world" and rec["request_id"] == "req-42"
    assert rec["level"] == "INFO" and rec["logger"] == "stockcast.test"
