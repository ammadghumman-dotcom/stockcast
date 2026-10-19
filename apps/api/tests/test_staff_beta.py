"""Staff Beta page API: hidden from non-staff, invites by email, beta grant, feedback."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, Feedback, Organization, User, WaitlistSignup
from app.services import beta as beta_svc


@pytest.fixture
def staff(monkeypatch, headers):
    monkeypatch.setattr(settings, "staff_emails", "Boss@Stockcast.app, other@stockcast.app")
    return {**headers, "X-User-Email": "boss@stockcast.app"}


@pytest.fixture
def waitlist(db):
    db.add_all(
        [
            WaitlistSignup(
                email="fit@candles.co",
                name="Sara",
                company="Candle Co",
                channels=["shopify", "amazon"],
                makes_products=True,
            ),
            WaitlistSignup(email="reseller@x.co", channels=["shopify", "ebay"]),
        ]
    )
    db.flush()


def test_staff_routes_are_invisible_to_everyone_else(client, headers, waitlist) -> None:
    assert client.get("/staff/me", headers=headers).json() == {"staff": False}
    assert client.get("/staff/beta/waitlist", headers=headers).status_code == 404
    other = {**headers, "X-User-Email": "customer@shop.co"}
    r = client.post("/staff/beta/invites", json={"emails": ["fit@candles.co"]}, headers=other)
    assert r.status_code == 404


def test_waitlist_and_invites(client, db, staff, waitlist, monkeypatch) -> None:
    assert client.get("/staff/me", headers=staff).json() == {"staff": True}
    rows = client.get("/staff/beta/waitlist", headers=staff).json()
    assert [r["email"] for r in rows] == ["fit@candles.co"] and rows[0]["beta_fit"] is True
    assert len(client.get("/staff/beta/waitlist?all=true", headers=staff).json()) == 2

    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(__import__("json").loads(request.content))
        return httpx.Response(200, json={"id": "em_1"})

    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(
        beta_svc, "_http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    body = {"emails": ["FIT@candles.co", "nobody@x.co"]}
    out = client.post("/staff/beta/invites", json=body, headers=staff).json()
    assert out == {
        "sent": ["fit@candles.co"],
        "skipped": [],
        "failed": [],
        "unknown": ["nobody@x.co"],
    }
    assert sent[0]["to"] == ["fit@candles.co"] and "Sara" in sent[0]["html"]
    assert "Candle Co" in sent[0]["html"] and "/sign-up?beta=1" in sent[0]["html"]
    assert sent[0]["reply_to"] == "boss@stockcast.app"
    row = db.scalar(select(WaitlistSignup).where(WaitlistSignup.email == "fit@candles.co"))
    assert row.beta_invited_at is not None

    # a second click never emails twice unless resend is asked for
    again = client.post("/staff/beta/invites", json=body, headers=staff).json()
    assert again["sent"] == [] and again["skipped"] == ["fit@candles.co"] and len(sent) == 1
    body2 = {"emails": ["fit@candles.co"], "resend": True}
    assert client.post("/staff/beta/invites", json=body2, headers=staff).json()["sent"]
    assert {a.action for a in db.scalars(select(AuditLog))} >= {"staff.beta_invite"}


def test_failed_send_is_not_marked_invited(client, db, staff, waitlist, monkeypatch) -> None:
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(
        beta_svc,
        "_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(422))),
    )
    out = client.post("/staff/beta/invites", json={"emails": ["fit@candles.co"]}, headers=staff)
    assert out.json()["failed"] == ["fit@candles.co"]
    row = db.scalar(select(WaitlistSignup).where(WaitlistSignup.email == "fit@candles.co"))
    assert row.beta_invited_at is None


def test_grant_workspaces_and_feedback(client, db, org, staff) -> None:
    db.add(User(org_id=org.id, email="owner@acme.co", name="Owner", role="owner"))
    db.add(Feedback(org_id=org.id, actor="owner@acme.co", rating=5, message="love it", page="/"))
    db.flush()
    r = client.post("/staff/beta/grant", json={"key": "owner@acme.co"}, headers=staff)
    assert r.status_code == 200 and r.json()["is_beta"] is True
    assert [w["slug"] for w in client.get("/staff/beta/workspaces", headers=staff).json()] == [
        org.slug
    ]
    r = client.post("/staff/beta/grant", json={"key": org.slug, "on": False}, headers=staff)
    assert r.json()["is_beta"] is False
    assert client.post("/staff/beta/grant", json={"key": "nope"}, headers=staff).status_code == 404
    fb = client.get("/staff/beta/feedback", headers=staff).json()
    assert fb[0]["message"] == "love it" and fb[0]["workspace"] == org.name


def test_invited_signup_gets_beta_automatically(db, org) -> None:
    db.add(
        WaitlistSignup(email="fit@candles.co", channels=["shopify", "amazon"], makes_products=True)
    )
    db.flush()
    assert beta_svc.flag_invited_workspace(db, org, "fit@candles.co") is False  # not invited yet
    row = db.scalar(select(WaitlistSignup))
    row.beta_invited_at = __import__("datetime").datetime.now(__import__("datetime").UTC)
    db.flush()
    assert beta_svc.flag_invited_workspace(db, org, "FIT@candles.co") is True
    assert db.get(Organization, org.id).is_beta is True
