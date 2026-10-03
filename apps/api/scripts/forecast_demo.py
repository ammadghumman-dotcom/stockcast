"""Forecast the demo org and print the backtest summary.  uv run python -m scripts.forecast_demo"""

from datetime import date

from sqlalchemy import select

from app.db import SessionLocal
from app.forecast.engine import run_forecast
from app.forecast.models import chronos_available
from app.models import ForecastAccuracy, ForecastRun, Product
from scripts.seed import DEMO_ORG_ID

if __name__ == "__main__":
    print("chronos available:", chronos_available())
    with SessionLocal() as db:
        run = ForecastRun(org_id=DEMO_ORG_ID, trigger="manual", horizon_days=90)
        db.add(run)
        db.commit()
        run = run_forecast(db, run, as_of=date.today())
        print(
            f"status={run.status} skus={run.skus_total} chronos={run.skus_chronos} "
            f"croston={run.skus_croston} fallback={run.skus_fallback} WAPE={run.wape}"
        )
        rows = db.execute(
            select(Product.sku, ForecastAccuracy)
            .join(Product, Product.id == ForecastAccuracy.product_id)
            .where(ForecastAccuracy.run_id == run.id)
            .order_by(ForecastAccuracy.wape)
        ).all()
        for sku, a in rows:
            print(
                f"  {sku:14s} {a.model:8s} wape={a.wape} mape={a.mape} "
                f"chronos={a.wape_chronos} stats={a.wape_stats}"
            )
