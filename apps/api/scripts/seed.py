"""Seed a demo organization: 20 finished SKUs, 3 raw materials, 1 BOM, 365 days of sales.

Usage:  uv run python -m scripts.seed   (idempotent: re-running resets the demo org)

The catalogue and sales generator live in app/services/sample_data.py, shared with the
"explore with sample data" option new workspaces get during onboarding.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Organization, Region, User
from app.services.sample_data import BOM_LINES, build

DEMO_ORG_ID = uuid.UUID("00000000-0000-0000-0000-00000000d3a0")
DEMO_SLUG = "demo-candle-co"


def reset_demo_org(db: Session) -> Organization:
    existing = db.scalar(select(Organization).where(Organization.id == DEMO_ORG_ID))
    if existing:
        db.execute(delete(Organization).where(Organization.id == DEMO_ORG_ID))  # cascades
        db.commit()
    org = Organization(
        id=DEMO_ORG_ID,
        name="Demo Candle Co",
        slug=DEMO_SLUG,
        plan="scale",  # demo org: no limits, no trial countdown
        plan_status="active",
    )
    db.add(org)
    db.commit()
    return org


def seed(db: Session, *, days: int = 365, today: date | None = None, seed_value: int = 42) -> None:
    org = reset_demo_org(db)
    oid = org.id
    db.add(User(org_id=oid, email="owner@demo-candle.co", name="Demo Owner", role="owner"))
    regions = {
        code: Region(org_id=oid, code=code, name=name, currency=cur)
        for code, name, cur in [("US", "United States", "USD"), ("AE", "UAE", "AED")]
    }
    db.add_all(regions.values())
    db.flush()
    stats = build(
        db,
        oid,
        region=regions["US"],
        holiday_regions=list(regions.values()),
        days=days,
        today=today,
        seed_value=seed_value,
    )
    db.commit()
    print(
        f"Seeded org {org.slug} ({org.id}): {stats['products']} products, "
        f"{len(BOM_LINES)} BOM lines, {stats['sales_rows']} sales rows over {days} days"
    )


if __name__ == "__main__":
    with SessionLocal() as session:
        seed(session)
