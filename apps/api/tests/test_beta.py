"""Beta program: feedback endpoint and ops script."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.models import Feedback, Organization, User, WaitlistSignup
from scripts import beta


def test_feedback_is_stored_per_workspace(client, db, org, headers) -> None:
    r = client.post(
        "/feedback",
        json={"message": "Need lead times per supplier", "rating": 4, "page": "/recommendations"},
        headers=headers,
    )
    assert r.status_code == 201
    fb = db.scalar(select(Feedback))
    assert fb.org_id == org.id and fb.rating == 4 and fb.page == "/recommendations"
    assert client.post("/feedback", json={"message": "x"}, headers=headers).status_code == 422
    assert (
        client.post("/feedback", json={"message": "ok?", "rating": 9}, headers=headers).status_code
        == 422
    )


def test_beta_candidates_grant_and_invites(db, org) -> None:
    db.add_all(
        [
            WaitlistSignup(
                email="fit@candles.co", channels=["shopify", "amazon"], makes_products=True
            ),
            WaitlistSignup(
                email="reseller@x.co", channels=["shopify", "amazon"], makes_products=False
            ),
            WaitlistSignup(email="single@x.co", channels=["shopify"], makes_products=True),
        ]
    )
    db.add(User(org_id=org.id, email="owner@acme.co", name="Owner", role="owner"))
    db.flush()
    assert [r.email for r in beta.candidates(db)] == ["fit@candles.co"]
    assert len(beta.candidates(db, include_all=True)) == 3

    assert beta.grant(db, org.slug).is_beta is True
    other = Organization(name="Shop", slug="shop-co", shopify_shop="shop-co.myshopify.com")
    db.add(other)
    db.flush()
    assert beta.grant(db, "shop-co.myshopify.com").id == other.id
    assert beta.find_org(db, "owner@acme.co").id == org.id
    assert beta.grant(db, "nobody") is None

    when = datetime(2026, 10, 6, tzinfo=UTC)
    assert beta.mark_invited(db, ["FIT@candles.co", "missing@x.co"], now=when) == 1
    assert (
        db.scalar(
            select(WaitlistSignup.beta_invited_at).where(WaitlistSignup.email == "fit@candles.co")
        )
        == when
    )
