"""Nightly-window benchmark: how fast does run_forecast go, and will 50 x 2,000 SKUs fit?

    uv run python -m scripts.bench_forecast            # after scripts.seed_load (any size)
    uv run python -m scripts.bench_forecast --orgs 2   # only the first N load orgs

Prints SKUs/second per worker process and the projected wall time for the full fleet at
CELERY_CONCURRENCY workers, which is what the RUNBOOK's load-test section records.
"""

from __future__ import annotations

import argparse
import math
import os
import time

from sqlalchemy import select

from app.db import SessionLocal
from app.forecast.engine import run_forecast
from app.models import ForecastRun, Organization

TARGET_ORGS, TARGET_SKUS, WINDOW_MIN = 50, 2000, 60  # beat: forecast 03:30 -> planning 04:30 UTC


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orgs", type=int, default=0)
    ap.add_argument("--workers", type=int, default=int(os.environ.get("CELERY_CONCURRENCY", 2)))
    a = ap.parse_args()
    with SessionLocal() as db:
        orgs = db.scalars(
            select(Organization).where(Organization.slug.like("load-%")).order_by(Organization.slug)
        ).all()
        if a.orgs:
            orgs = orgs[: a.orgs]
        if not orgs:
            raise SystemExit("no load orgs: run scripts.seed_load first")
        total_skus = 0
        t0 = time.perf_counter()
        for org in orgs:
            run = ForecastRun(org_id=org.id, trigger="bench", horizon_days=90)
            db.add(run)
            db.flush()
            t = time.perf_counter()
            run_forecast(db, run)
            dt = time.perf_counter() - t
            total_skus += run.skus_total
            print(
                f"{org.slug}: {run.skus_total} SKUs in {dt:.1f}s "
                f"({run.skus_total / max(dt, 1e-6):.1f} SKU/s) wape={run.wape} "
                f"chronos={run.skus_chronos} croston={run.skus_croston} "
                f"fallback={run.skus_fallback}"
            )
        elapsed = time.perf_counter() - t0
    rate = total_skus / elapsed
    fleet = TARGET_ORGS * TARGET_SKUS
    projected_min = fleet / rate / 60 / a.workers
    needed = math.ceil(fleet / rate / 60 / WINDOW_MIN)
    print(
        f"\n[bench] {total_skus} SKUs in {elapsed:.0f}s = {rate:.1f} SKU/s per worker process\n"
        f"[bench] projected {fleet:,} SKUs on {a.workers} workers: {projected_min:.0f} min "
        f"(window {WINDOW_MIN} min) -> {'OK' if projected_min <= WINDOW_MIN else 'TOO SLOW'}\n"
        f"[bench] worker processes needed for the window: {needed} "
        f"(orgs fan out one Celery task each, so processes can span replicas)"
    )


if __name__ == "__main__":
    main()
