"""Activation milestones, PostHog capture and the weekly cohort report."""

import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app import analytics, analytics_tasks
from app.config import settings
from app.models import Organization, OrgMilestone, Product, ProductType


@pytest.fixture
def captured(monkeypatch):
    """Turn PostHog on and collect queued payloads instead of sending them."""
    events: list[dict] = []
    monkeypatch.setattr(settings, "posthog_api_key", "phc_test")
    monkeypatch.setattr(
        analytics_tasks.capture_event, "delay", lambda payload: events.append(payload)
    )
    return events


def _milestones(db, org) -> list[str]:
    return sorted(db.scalars(select(OrgMilestone.key).where(OrgMilestone.org_id == org.id)))


def test_reach_is_once_per_workspace(db, org, other_org) -> None:
    assert analytics.reach(db, org.id, "first_po_created") is True
    assert analytics.reach(db, org.id, "first_po_created") is False
    assert analytics.reach(db, other_org.id, "first_po_created") is True


def test_no_posthog_key_still_records_milestones(db, org, monkeypatch) -> None:
    monkeypatch.setattr(settings, "posthog_api_key", "")
    assert analytics.track(db, org.id, "po_created", props={"count": 2}) is True
    assert _milestones(db, org) == ["first_po_created"]


def test_forecast_view_captures_only_the_first(client, db, org, headers, captured) -> None:
    p = Product(org_id=org.id, sku="C1", name="Candle", type=ProductType.finished)
    db.add(p)
    db.flush()
    for _ in range(3):
        client.get("/forecasts", params={"product_id": str(p.id)}, headers=headers)
    assert _milestones(db, org) == ["first_forecast_viewed"]
    assert [e["event"] for e in captured] == ["first_forecast_viewed"]
    assert captured[0]["distinct_id"] == f"org:{org.id}"
    assert captured[0]["properties"]["$groups"] == {"organization": str(org.id)}


def test_channel_connect_event_and_first_milestone(client, db, org, headers, captured) -> None:
    body = {
        "name": "Woo",
        "type": "woocommerce",
        "credentials": {
            "url": "https://shop.example",
            "consumer_key": "ck",
            "consumer_secret": "cs",
        },
    }
    assert client.post("/channels", json=body, headers=headers).status_code == 201
    assert (
        client.post("/channels", json={**body, "name": "Woo 2"}, headers=headers).status_code == 201
    )
    names = [e["event"] for e in captured]
    assert names == ["channel_connected", "first_channel_connected", "channel_connected"]
    assert [e["properties"]["first"] for e in captured] == [True, True, False]
    assert captured[0]["properties"]["type"] == "woocommerce"


def test_capture_event_posts_to_posthog(monkeypatch) -> None:
    sent = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json={"status": "Ok"})

    monkeypatch.setattr(
        analytics_tasks, "_http", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    analytics_tasks.capture_event.run({"event": "x", "distinct_id": "org:1", "api_key": "k"})
    assert sent[0][0] == f"{settings.posthog_host}/i/v0/e/"
    assert sent[0][1]["event"] == "x"


def _org_at(db, slug: str, when: datetime) -> Organization:
    o = Organization(name=slug, slug=slug)
    db.add(o)
    db.flush()
    o.created_at = when
    db.flush()
    return o


def test_cohorts_and_report(db, monkeypatch) -> None:
    today = date(2026, 10, 7)  # Wednesday; cohort weeks start Monday Oct 5
    this_week = datetime(2026, 10, 5, 12, tzinfo=UTC)
    last_week = this_week - timedelta(days=7)
    a = _org_at(db, "a-co", this_week)
    _org_at(db, "b-co", this_week)
    c = _org_at(db, "c-co", last_week)
    analytics.reach(db, a.id, "first_channel_connected")
    analytics.reach(db, a.id, "first_po_created")
    analytics.reach(db, c.id, "first_channel_connected")
    db.flush()

    rows = analytics_tasks.cohorts(db, weeks=3, today=today)
    assert [r.week for r in rows] == [date(2026, 10, 5), date(2026, 9, 28), date(2026, 9, 21)]
    assert rows[0].orgs >= 2 and rows[0].reached["first_po_created"] == 1
    assert rows[1].reached == {"first_channel_connected": 1}
    assert rows[2].orgs == 0 and rows[2].pct("first_po_created") == 0.0

    text, table = analytics_tasks.render(rows)
    assert text.splitlines()[0].startswith("Signup week | Workspaces | Connected")
    assert "<table" in table and "2026-10-05" in table

    posts = []
    monkeypatch.setattr(settings, "report_emails", "ops@x.co, founder@x.co")
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "alert_webhook_url", "https://hooks.example/abc")
    monkeypatch.setattr(
        analytics_tasks,
        "_http",
        lambda: httpx.Client(
            transport=httpx.MockTransport(
                lambda r: posts.append((r.url.host, json.loads(r.content))) or httpx.Response(200)
            )
        ),
    )
    monkeypatch.setattr(analytics_tasks, "SessionLocal", lambda: _Ctx(db))
    analytics_tasks.weekly_cohort_report.run()
    hosts = [h for h, _ in posts]
    assert hosts == ["api.resend.com", "hooks.example"]
    assert posts[0][1]["to"] == ["ops@x.co", "founder@x.co"]


class _Ctx:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *a):
        return False


def test_milestone_table_is_org_scoped(db, org, other_org) -> None:
    analytics.reach(db, org.id, "first_channel_connected")
    n = db.scalar(
        select(func.count()).select_from(OrgMilestone).where(OrgMilestone.org_id == other_org.id)
    )
    assert n == 0
