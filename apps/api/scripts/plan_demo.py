"""Plan the demo org from its latest forecast and print recommendations.

uv run python -m scripts.plan_demo   (run `make seed` and `make forecast` first)
"""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import PlanningRun, Product, Recommendation
from app.planning.engine import run_planning
from scripts.seed import DEMO_ORG_ID

if __name__ == "__main__":
    with SessionLocal() as db:
        run = PlanningRun(org_id=DEMO_ORG_ID, trigger="manual")
        db.add(run)
        db.commit()
        run = run_planning(db, run)
        print(
            f"status={run.status} products={run.products_total} reorder={run.n_reorder} "
            f"produce={run.n_produce} health={run.health_counts} cash={run.cash_by_health}"
        )
        rows = db.execute(
            select(Product.sku, Recommendation)
            .join(Product, Product.id == Recommendation.product_id)
            .where(Recommendation.run_id == run.id)
            .order_by(Recommendation.order_by_date.asc().nulls_last())
        ).all()
        for sku, r in rows:
            print(f"  {sku:14s} {r.health:9s} {r.action:8s} {r.reason}")
