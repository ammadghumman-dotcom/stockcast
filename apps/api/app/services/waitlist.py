"""Waitlist / beta applications from the public site."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import WaitlistSignup

CHANNELS = ("shopify", "amazon", "ebay", "woocommerce", "etsy", "wholesale", "other")


def beta_fit(channels: list[str], makes_products: bool) -> bool:
    """Beta target: brands that make/assemble what they sell and sell on 2+ channels."""
    return makes_products and len(set(channels)) >= 2


def join(
    db: Session,
    *,
    email: str,
    name: str | None,
    company: str | None,
    website: str | None,
    channels: list[str],
    makes_products: bool,
    notes: str | None,
    source: str,
) -> WaitlistSignup:
    """Insert or refresh (same email again updates the answers; first-seen date is kept)."""
    values = {
        "email": email.strip().lower(),
        "name": name,
        "company": company,
        "website": website,
        "channels": sorted({c for c in channels if c in CHANNELS}),
        "makes_products": makes_products,
        "notes": notes,
        "source": source,
    }
    stmt = pg_insert(WaitlistSignup).values(**values)
    update = {k: stmt.excluded[k] for k in values if k != "email"}
    db.execute(stmt.on_conflict_do_update(constraint="uq_waitlist_signups_email", set_=update))
    row = db.scalar(select(WaitlistSignup).where(WaitlistSignup.email == values["email"]))
    assert row is not None
    return row
