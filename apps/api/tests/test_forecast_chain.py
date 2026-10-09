"""Forecast -> planning chaining and region fallback (staging bugs #15 and #16)."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.forecast import covariates as cov
from app.models import (
    CategoryHolidayUplift,
    Channel,
    ChannelType,
    PlanningRun,
    Product,
    ProductCategory,
    Region,
    SalesDaily,
)


def test_then_plan_queues_planning_after_a_successful_forecast(
    client, db, headers, org, monkeypatch
) -> None:
    monkeypatch.setattr("app.forecast.router.chronos_available", lambda: False)
    r = client.post("/forecast-runs", params={"horizon": 14}, headers=headers)
    assert r.status_code == 202 and r.json()["status"] == "success"
    assert db.scalars(select(PlanningRun).where(PlanningRun.org_id == org.id)).all() == []

    r = client.post("/forecast-runs", params={"horizon": 14, "then_plan": "true"}, headers=headers)
    assert r.status_code == 202 and r.json()["status"] == "success"
    runs = db.scalars(select(PlanningRun).where(PlanningRun.org_id == org.id)).all()
    assert [p.trigger for p in runs] == ["after_forecast"]
    assert runs[0].status == "success", runs[0].error


def test_then_plan_skips_planning_when_the_forecast_fails(
    client, db, headers, org, monkeypatch
) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("model crashed")

    monkeypatch.setattr("app.forecast.engine.load_series", boom)
    r = client.post("/forecast-runs", params={"then_plan": "true"}, headers=headers)
    assert r.json()["status"] == "failed"
    assert db.scalars(select(PlanningRun).where(PlanningRun.org_id == org.id)).all() == []


def _csv_world(db, org):
    region = Region(org_id=org.id, code="US", name="United States")
    channel = Channel(org_id=org.id, name="CSV Import", type=ChannelType.csv)  # no region
    product = Product(org_id=org.id, sku="CND", name="Candle", type="finished")
    db.add_all([region, channel, product])
    db.flush()
    as_of = date(2026, 10, 8)
    for i in range(30):
        db.add(
            SalesDaily(
                org_id=org.id,
                date=as_of - timedelta(days=i),
                product_id=product.id,
                channel_id=channel.id,
                units=Decimal(5),
                revenue=Decimal(50),
            )
        )
    db.flush()
    return region, product, as_of


def test_sales_without_a_region_count_toward_the_home_region(db, org) -> None:
    region, product, as_of = _csv_world(db, org)
    shares = cov.load_region_shares(db, org.id, as_of)
    assert shares[product.id] == {region.id: 1.0}
    assert shares["__default__"] == {region.id: 1.0}


def test_regioned_sales_still_win_over_the_fallback(db, org) -> None:
    region, product, as_of = _csv_world(db, org)
    pk = Region(org_id=org.id, code="PK", name="Pakistan")
    db.add(pk)
    db.flush()
    shop = Channel(org_id=org.id, name="Shop", type=ChannelType.shopify, region_id=pk.id)
    db.add(shop)
    db.flush()
    db.add(
        SalesDaily(
            org_id=org.id,
            date=as_of,
            product_id=product.id,
            channel_id=shop.id,
            units=Decimal(50),
            revenue=Decimal(500),
        )
    )
    db.flush()
    shares = cov.load_region_shares(db, org.id, as_of)
    # 150 CSV units follow the largest regioned channel (PK), not the first-created region
    assert shares[product.id] == {pk.id: 1.0}


def test_learning_never_overwrites_a_manual_uplift(db, org) -> None:
    region = Region(org_id=org.id, code="US", name="United States")
    cat = ProductCategory(org_id=org.id, name="Candles")
    db.add_all([region, cat])
    db.flush()
    row = CategoryHolidayUplift(
        org_id=org.id,
        category_id=cat.id,
        region_id=region.id,
        event_name="Christmas",
        uplift_pct=Decimal("50.00"),
        learned=False,
        sample_size=0,
        manual=True,
    )
    db.add(row)
    db.flush()
    learned = {(cat.id, region.id, "Christmas"): cov.Uplift(1.02, learned=True, sample_size=2)}
    cov.persist_uplifts(
        db,
        org.id,
        learned,
        cat_ids={cat.id},
        regions=[region.id],
        event_names={"Christmas"},
        category_names={cat.id: "Candles"},
    )
    db.refresh(row)
    assert row.uplift_pct == Decimal("50.00") and row.manual and not row.learned
