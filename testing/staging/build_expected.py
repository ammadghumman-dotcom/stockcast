"""Run the staging test script against a LOCAL scratch database and record the results.

This is how expected_results.json was produced: it performs, through the HTTP API, exactly the
setup steps the test cases ask the agent to do on staging (import CSVs, add suppliers, set
preferred suppliers and planning settings, run forecast + planning), then saves what came out.

Run from apps/api with a throwaway database (it is written to, not rolled back):
  DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/stockcast_qa \\
  AUTH_MODE=header CELERY_TASK_ALWAYS_EAGER=true RATE_LIMIT_ENABLED=false \\
  uv run alembic upgrade head && uv run python ../../testing/staging/build_expected.py [--end YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Supplier setup the test cases perform by hand (Settings -> Suppliers, then each product's
# planning panel). Kept here so the expected file and the cases cannot drift apart.
SUPPLIERS = {
    "maker": [
        {"name": "QA Wax Supplier", "email": "qa-wax@example.com", "lead_time_days": 21, "moq": 100},
        {"name": "QA Glass Co", "email": "qa-glass@example.com", "lead_time_days": 30, "moq": 500},
        {"name": "QA Wick Co", "email": "qa-wick@example.com", "lead_time_days": 14, "moq": 1000},
    ],
    "reseller": [
        {"name": "QA Vendor Alpha", "email": "qa-alpha@example.com", "lead_time_days": 10, "moq": 50},
        {"name": "QA Vendor Beta", "email": "qa-beta@example.com", "lead_time_days": 20, "moq": 200},
    ],
}
PREFERRED = {
    "maker": {"QA-WAX-SOY": "QA Wax Supplier", "QA-JAR-8OZ": "QA Glass Co", "QA-WICK-CT": "QA Wick Co"},
    "reseller": {
        "QA-GFT-MUG": "QA Vendor Alpha",
        "QA-GFT-TOTE": "QA Vendor Alpha",
        "QA-GFT-CARD": "QA Vendor Beta",
        "QA-GFT-BOX": "QA Vendor Beta",
    },
}
SETTINGS = {"service_level": "0.95", "default_lead_time_days": 14, "production_lead_time_days": 7,
            "target_cover_days": 30}

KEEP = ["sku", "action", "health", "qty", "order_by_date", "supplier_name", "daily_demand",
        "lead_time_days", "safety_stock", "reorder_point", "on_hand", "stockout_date",
        "days_of_cover", "reason"]


def run(kind: str, client, end: date) -> dict:
    from app.db import SessionLocal
    from app.models import Organization

    with SessionLocal() as db:
        org = Organization(id=uuid.uuid4(), name=f"QA {kind}", slug=f"qa-{kind}-{uuid.uuid4().hex[:6]}")
        db.add(org)
        db.commit()
        h = {"X-Org-Id": str(org.id), "X-Role": "owner"}

    folder = HERE / kind
    files = {k: (f"{k}.csv", (folder / f"{k}.csv").read_bytes(), "text/csv")
             for k in ("products", "sales", "inventory", "bom") if (folder / f"{k}.csv").exists()}
    r = client.post("/imports", headers=h, files=files)
    r.raise_for_status()
    imported = r.json()

    sup_ids = {}
    for s in SUPPLIERS[kind]:
        r = client.post("/suppliers", headers=h, json=s)
        r.raise_for_status()
        sup_ids[s["name"]] = r.json()["id"]
    products = {p["sku"]: p for p in client.get("/products", headers=h, params={"limit": 500}).json()}
    for sku, sup in PREFERRED[kind].items():
        r = client.patch(f"/products/{products[sku]['id']}/planning", headers=h,
                         json={"preferred_supplier_id": sup_ids[sup]})
        r.raise_for_status()
    client.patch("/planning-settings", headers=h, json=SETTINGS).raise_for_status()

    fr = client.post("/forecast-runs", headers=h)
    fr.raise_for_status()
    runs = client.get("/forecast-runs", headers=h).json()
    pr = client.post("/planning-runs", headers=h)
    pr.raise_for_status()
    recs = client.get("/recommendations", headers=h, params={"limit": 500}).json()
    return {
        "import": imported,
        "forecast_run_status": runs[0]["status"] if runs else None,
        "recommendations": sorted(
            ({k: rec.get(k) for k in KEEP} for rec in recs), key=lambda x: x["sku"] or ""
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", type=date.fromisoformat, default=date.today())
    a = ap.parse_args()
    subprocess.run([sys.executable, str(HERE / "make_data.py"), "--end", a.end.isoformat()], check=True)

    from fastapi.testclient import TestClient

    from app.forecast.models import chronos_available
    from app.main import app

    with TestClient(app) as client:
        out = {
            "generated_for": a.end.isoformat(),
            "models": "chronos+autoets" if chronos_available() else "autoets only (no chronos)",
            "settings": SETTINGS,
            "suppliers": SUPPLIERS,
            "preferred": PREFERRED,
            "maker": run("maker", client, a.end),
            "reseller": run("reseller", client, a.end),
        }
    (HERE / "expected_results.json").write_text(json.dumps(out, indent=2, default=str) + "\n")
    print("wrote expected_results.json")


if __name__ == "__main__":
    main()
