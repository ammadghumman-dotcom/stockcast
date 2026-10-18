"""Staging regression: sales uploaded up to Oct 8, forecast on Oct 17 -> p50 collapsed to 0.

Days after the workspace's newest sales day are unobserved, not zero demand.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import numpy as np

from app.forecast.engine import run_forecast
from app.forecast.features import load_series, org_data_through
from app.models import (
    Channel,
    Forecast,
    ForecastRun,
    InventoryLevel,
    Location,
    Organization,
    Product,
    SalesDaily,
)
from app.models.enums import ChannelType, ProductType

AS_OF = date(2026, 10, 17)


def _org(db, *, last_day: date, quiet_sku_last_day: date | None = None):
    org = Organization(id=uuid.uuid4(), name="Stale", slug=f"stale-{uuid.uuid4().hex[:6]}")
    db.add(org)
    db.flush()
    ch = Channel(org_id=org.id, name="CSV", type=ChannelType.csv)
    lav = Product(org_id=org.id, sku="LAV", name="Lavender", type=ProductType.finished)
    db.add_all([ch, lav])
    quiet = None
    if quiet_sku_last_day:
        quiet = Product(org_id=org.id, sku="QUIET", name="Quiet", type=ProductType.finished)
        db.add(quiet)
    db.flush()
    rows = []
    for i in range(120):
        d = last_day - timedelta(days=i)
        rows.append(
            SalesDaily(
                org_id=org.id,
                date=d,
                product_id=lav.id,
                channel_id=ch.id,
                units=Decimal(20),
                revenue=Decimal(480),
            )
        )
        if quiet is not None and quiet_sku_last_day and d <= quiet_sku_last_day:
            rows.append(
                SalesDaily(
                    org_id=org.id,
                    date=d,
                    product_id=quiet.id,
                    channel_id=ch.id,
                    units=Decimal(10),
                    revenue=Decimal(100),
                )
            )
    db.add_all(rows)
    # everything is in stock, so trailing zeros are not stockouts
    loc = Location(org_id=org.id, name="WH")
    db.add(loc)
    db.flush()
    for p in (lav, quiet):
        if p is not None:
            db.add(InventoryLevel(org_id=org.id, product_id=p.id, location_id=loc.id, on_hand=500))
    db.flush()
    return org, lav, quiet


def test_days_after_the_newest_upload_are_masked_not_zero(db) -> None:
    org, lav, _ = _org(db, last_day=AS_OF - timedelta(days=9))
    assert org_data_through(db, org.id, AS_OF) == AS_OF - timedelta(days=9)
    (s,) = load_series(db, org.id, as_of=AS_OF)
    assert np.isnan(s.y[-9:]).all() and s.observed[-1] == 20

    run = ForecastRun(org_id=org.id)
    db.add(run)
    db.flush()
    run_forecast(db, run, as_of=AS_OF, use_covariates=False)
    assert run.status == "success", run.error
    assert run.data_through == AS_OF - timedelta(days=9)
    p50 = [float(f.p50) for f in db.query(Forecast).filter_by(run_id=run.id, product_id=lav.id)]
    assert p50 and abs(np.mean(p50) - 20) < 1.5  # was ~0 before the fix


def test_a_product_that_really_stopped_selling_still_reads_as_zero(db) -> None:
    # the org keeps uploading (LAV sells through AS_OF); QUIET stopped 20 days ago -> real zeros
    org, _, quiet = _org(db, last_day=AS_OF, quiet_sku_last_day=AS_OF - timedelta(days=20))
    series = {s.sku: s for s in load_series(db, org.id, as_of=AS_OF)}
    assert not np.isnan(series["QUIET"].y[-20:]).any()
    assert (series["QUIET"].y[-20:] == 0).all()
