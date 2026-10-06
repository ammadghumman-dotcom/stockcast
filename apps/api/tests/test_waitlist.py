"""Public waitlist / beta form."""

from sqlalchemy import func, select

from app.models import WaitlistSignup
from app.services.waitlist import beta_fit


def test_join_stores_and_flags_beta_fit(client, db) -> None:
    r = client.post(
        "/waitlist",
        json={
            "email": "Founder@Candleco.com",
            "company": "Candle Co",
            "channels": ["shopify", "amazon", "bogus"],
            "makes_products": True,
        },
    )
    assert r.status_code == 202 and r.json() == {"ok": True, "beta_fit": True}
    row = db.scalar(select(WaitlistSignup))
    assert row.email == "founder@candleco.com"
    assert row.channels == ["amazon", "shopify"]  # unknown channel dropped, sorted


def test_same_email_updates_instead_of_duplicating(client, db) -> None:
    client.post("/waitlist", json={"email": "a@b.co", "channels": ["shopify"]})
    r = client.post(
        "/waitlist",
        json={"email": "A@b.co", "channels": ["shopify", "ebay"], "makes_products": True},
    )
    assert r.json()["beta_fit"] is True
    assert db.scalar(select(func.count()).select_from(WaitlistSignup)) == 1
    assert db.scalar(select(WaitlistSignup.channels)) == ["ebay", "shopify"]


def test_honeypot_is_accepted_but_not_stored(client, db) -> None:
    r = client.post("/waitlist", json={"email": "bot@spam.io", "fax": "http://spam"})
    assert r.status_code == 202
    assert db.scalar(select(func.count()).select_from(WaitlistSignup)) == 0


def test_invalid_email_rejected(client) -> None:
    assert client.post("/waitlist", json={"email": "not-an-email"}).status_code == 422


def test_beta_fit_needs_making_and_two_channels() -> None:
    assert beta_fit(["shopify", "amazon"], True)
    assert not beta_fit(["shopify", "shopify"], True)
    assert not beta_fit(["shopify", "amazon"], False)
