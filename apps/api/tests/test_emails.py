"""Transactional email: templates render, sends are deduped, Resend is called once."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import emails
from app.config import settings
from app.models import Channel, ChannelType, EmailLog, Organization, PlanningRun, SyncRun, User
from app.planning.engine import run_planning
from tests.conftest import PLANNING_AS_OF


class FakeResend:
    def __init__(self) -> None:
        self.sent: list[httpx.Request] = []
        transport = httpx.MockTransport(self._handle)
        self.client = httpx.Client(transport=transport)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        return httpx.Response(200, json={"id": f"re_{len(self.sent)}"})


def _fake(monkeypatch) -> FakeResend:
    fake = FakeResend()
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(emails, "_http_client", lambda: fake.client)
    return fake


def _admin(db, org: Organization, email="ops@example.com", role="admin") -> User:
    u = User(org_id=org.id, email=email, name="Ops", role=role)
    db.add(u)
    db.flush()
    return u


def test_welcome_on_org_create_and_dedupe(client: TestClient, db, monkeypatch) -> None:
    fake = _fake(monkeypatch)
    r = client.post("/orgs", json={"name": "Bloom Co", "email": "founder@example.com"})
    assert r.status_code == 201, r.text
    assert len(fake.sent) == 1
    body = fake.sent[0].read().decode()
    assert "founder@example.com" in body and "Welcome to Stockcast" in body
    assert fake.sent[0].headers["Authorization"] == "Bearer re_test"
    org = db.get(Organization, r.json()["id"])
    assert emails.send_welcome(db, org, "founder@example.com") is None  # already sent
    assert len(fake.sent) == 1
    log = db.scalar(select(EmailLog).where(EmailLog.org_id == org.id))
    assert (log.kind, log.status, log.provider_id) == ("welcome", "sent", "re_1")


def test_without_api_key_mail_is_logged_as_skipped(db, org: Organization) -> None:
    _admin(db, org, role="owner")  # welcome goes to owners
    row = emails.send_welcome(db, org)
    assert row is not None and row.status == "skipped"


def test_trial_ending_selection_and_mail(db, org: Organization, monkeypatch) -> None:
    fake = _fake(monkeypatch)
    _admin(db, org)
    _admin(db, org, "viewer@example.com", "viewer")  # viewers don't get billing mail
    now = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
    org.trial_ends_at = now + timedelta(days=3)
    db.flush()
    assert [(o.id, d) for o, d in emails.trial_ending_orgs(db, now)] == [(org.id, 3)]
    assert emails.trial_ending_orgs(db, now - timedelta(days=1)) == []  # 4 days out: no mail
    assert emails.send_trial_ending(db, org, 3) is not None
    assert emails.send_trial_ending(db, org, 3) is None  # same day-left: deduped
    assert len(fake.sent) == 1
    sent = fake.sent[0].read().decode()
    assert "ops@example.com" in sent and "viewer@example.com" not in sent
    assert "ends in 3 days" in sent
    org.trial_ends_at = now + timedelta(hours=20)
    db.flush()
    assert [d for _, d in emails.trial_ending_orgs(db, now)] == [1]


def test_sync_failed_mail(db, org: Organization, monkeypatch) -> None:
    fake = _fake(monkeypatch)
    _admin(db, org)
    ch = Channel(org_id=org.id, name="Shop", type=ChannelType.shopify)
    db.add(ch)
    db.flush()
    run = SyncRun(org_id=org.id, channel_id=ch.id, trigger="manual", attempts=5)
    run.error = "ConnectorError: 401 from Shopify"
    db.add(run)
    db.flush()
    assert emails.send_sync_failed(db, run) is not None
    assert emails.send_sync_failed(db, run) is None
    assert len(fake.sent) == 1
    assert "401 from Shopify" in fake.sent[0].read().decode()


def test_weekly_digest_lists_at_risk_skus(db, org: Organization, candle_world, monkeypatch) -> None:
    fake = _fake(monkeypatch)
    _admin(db, org, "viewer@example.com", "viewer")  # digest goes to everyone
    run = PlanningRun(org_id=org.id)
    db.add(run)
    db.flush()
    run_planning(db, run, as_of=PLANNING_AS_OF)
    db.commit()
    assert emails.latest_run_for_digest(db, org.id).id == run.id
    row = emails.send_weekly_digest(db, org, run, date(2026, 10, 5))
    assert row is not None and row.dedupe_key.endswith("2026-W41")
    body = fake.sent[0].read().decode()
    assert "Weekly stockout digest" in body and "WAX" in body  # wax is at risk in the candle world
    assert emails.send_weekly_digest(db, org, run, date(2026, 10, 6)) is None  # same ISO week
    assert emails.send_weekly_digest(db, org, run, date(2026, 10, 12)) is not None


def test_sync_task_notifies_on_non_retryable_failure(db, org: Organization, monkeypatch) -> None:
    """A PlanLimitError inside a sync fails the run, emails admins, and is not retried."""
    from app.ingest import tasks as ingest_tasks

    fake = _fake(monkeypatch)
    _admin(db, org)
    ch = Channel(org_id=org.id, name="Shop", type=ChannelType.shopify, credentials_encrypted=b"x")
    db.add(ch)
    db.flush()
    run = SyncRun(org_id=org.id, channel_id=ch.id, trigger="manual")
    db.add(run)
    db.flush()

    class Conn:
        def __init__(self, *_: object) -> None: ...

        def fetch_products(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(ingest_tasks, "connector_for", lambda channel: Conn())
    monkeypatch.setattr(ingest_tasks, "SessionLocal", lambda: _SessionCtx(db))
    try:
        ingest_tasks.sync_channel.apply(args=(str(run.id),)).get()
    except RuntimeError:
        pass
    db.refresh(run)
    assert run.status == "failed" and "boom" in (run.error or "")
    assert len(fake.sent) == 1 and "Sync failed" in fake.sent[0].read().decode()


class _SessionCtx:
    """Context manager handing out the test session without closing it."""

    def __init__(self, db) -> None:
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *exc):
        return False
