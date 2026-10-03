from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BomLine, Product, ProductType, SalesDaily
from scripts.seed import DEMO_ORG_ID, seed


def test_seed_is_idempotent_and_complete(db: Session) -> None:
    seed(db, days=60, today=date(2025, 12, 31))
    seed(db, days=60, today=date(2025, 12, 31))  # second run resets, does not duplicate

    finished = db.scalar(
        select(func.count())
        .select_from(Product)
        .where(Product.org_id == DEMO_ORG_ID, Product.type == ProductType.finished)
    )
    raw = db.scalar(
        select(func.count())
        .select_from(Product)
        .where(Product.org_id == DEMO_ORG_ID, Product.type == ProductType.raw_material)
    )
    assert finished == 20 and raw == 3
    assert db.scalar(select(func.count()).select_from(BomLine)) == 3
    days = db.scalar(select(func.count(func.distinct(SalesDaily.date))))
    assert days == 60


def test_seed_has_christmas_uplift(db: Session) -> None:
    seed(db, days=365, today=date(2025, 12, 31))
    dec = db.scalar(
        select(func.sum(SalesDaily.units)).where(
            SalesDaily.date.between(date(2025, 12, 1), date(2025, 12, 24))
        )
    )
    jun = db.scalar(
        select(func.sum(SalesDaily.units)).where(
            SalesDaily.date.between(date(2025, 6, 1), date(2025, 6, 24))
        )
    )
    assert dec > jun * Decimal("1.3")
