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


def test_seed_org_has_three_channels_with_combined_and_split_forecast(db: Session, monkeypatch):
    """Acceptance (Step 8): seeded org with 3 channels shows combined + per-channel forecasts."""
    from app.forecast.channels import load_channel_mix
    from app.forecast.engine import run_forecast
    from app.models import Channel, ForecastRun

    monkeypatch.setattr("app.forecast.router.chronos_available", lambda: False)
    seed(db, days=120, today=date(2025, 12, 31))
    channels = {
        c.type.value: c for c in db.scalars(select(Channel).where(Channel.org_id == DEMO_ORG_ID))
    }
    assert set(channels) == {"shopify", "amazon", "ebay"}
    run = ForecastRun(org_id=DEMO_ORG_ID, horizon_days=30)
    db.add(run)
    db.flush()
    run_forecast(db, run, as_of=date(2025, 12, 31), use_covariates=False)
    assert run.status == "success", run.error
    finished = db.scalars(
        select(Product.id).where(
            Product.org_id == DEMO_ORG_ID, Product.type == ProductType.finished
        )
    ).all()
    mix = load_channel_mix(db, DEMO_ORG_ID, run.id, list(finished))
    assert len(mix) == 20  # every finished SKU has a split; raw materials have none
    for pid, parts in mix.items():
        assert abs(sum(float(m["share"]) for m in parts) - 1) < 0.001, pid
        assert {m["channel_type"] for m in parts} == {"shopify", "amazon", "ebay"}
    # the seed sends ~50/35/15 of demand to shopify/amazon/ebay
    avg = {t: 0.0 for t in channels}
    for parts in mix.values():
        for m in parts:
            avg[m["channel_type"]] += float(m["share"]) / len(mix)
    assert avg["shopify"] > avg["amazon"] > avg["ebay"]
    assert abs(avg["shopify"] - 0.5) < 0.08 and abs(avg["ebay"] - 0.15) < 0.06
