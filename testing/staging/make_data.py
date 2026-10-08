"""Generate the two staging test data sets as CSV files.

Run:  python testing/staging/make_data.py [--end YYYY-MM-DD] [--days 400]

Sales history ends the day BEFORE --end (default: today), so a forecast run on --end sees
an up-to-date history. Demand is deliberately flat (same units every day) so every model
converges on the same daily demand and the expected results can be checked by hand.

Writes, next to this file:
  maker/   products.csv  sales.csv  inventory.csv  bom.csv      -> workspace "QA Candle Co"
  reseller/ products.csv  sales.csv  inventory.csv              -> workspace "QA Gift Shop"
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent

# sku, name, type, unit_cost, unit, category, units_per_day (0 = raw material, no direct sales)
MAKER_PRODUCTS = [
    ("QA-CAN-LAV", "QA Lavender Candle 8oz", "finished", "6.50", "unit", "Candles", 20),
    ("QA-CAN-VAN", "QA Vanilla Candle 8oz", "finished", "6.50", "unit", "Candles", 12),
    ("QA-CAN-OUD", "QA Oud Candle 8oz", "finished", "9.00", "unit", "Candles", 3),
    ("QA-WAX-SOY", "QA Soy Wax", "raw_material", "4.20", "kg", "Raw materials", 0),
    ("QA-JAR-8OZ", "QA Amber Jar 8oz", "raw_material", "0.85", "unit", "Raw materials", 0),
    ("QA-WICK-CT", "QA Cotton Wick", "raw_material", "0.05", "unit", "Raw materials", 0),
]
MAKER_STOCK = {
    "QA-CAN-LAV": 300, "QA-CAN-VAN": 600, "QA-CAN-OUD": 30,
    "QA-WAX-SOY": 200, "QA-JAR-8OZ": 500, "QA-WICK-CT": 5000,
}
# parent, component, qty per unit (every candle uses the same recipe)
MAKER_BOM = [
    (c, comp, q)
    for c in ("QA-CAN-LAV", "QA-CAN-VAN", "QA-CAN-OUD")
    for comp, q in (("QA-WAX-SOY", "0.227"), ("QA-JAR-8OZ", "1"), ("QA-WICK-CT", "1"))
]

RESELLER_PRODUCTS = [
    ("QA-GFT-MUG", "QA Ceramic Mug", "finished", "3.10", "unit", "Kitchen", 15),
    ("QA-GFT-TOTE", "QA Canvas Tote", "finished", "2.40", "unit", "Bags", 8),
    ("QA-GFT-CARD", "QA Greeting Card", "finished", "0.30", "unit", "Stationery", 40),
    ("QA-GFT-BOX", "QA Gift Box", "finished", "1.10", "unit", "Packaging", 5),
]
RESELLER_STOCK = {"QA-GFT-MUG": 200, "QA-GFT-TOTE": 400, "QA-GFT-CARD": 9000, "QA-GFT-BOX": 50}

PRICE = {  # retail price used for the revenue column
    "QA-CAN-LAV": 24, "QA-CAN-VAN": 24, "QA-CAN-OUD": 32,
    "QA-GFT-MUG": 14, "QA-GFT-TOTE": 12, "QA-GFT-CARD": 4, "QA-GFT-BOX": 5,
}


def _write(path: Path, header: list[str], rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def build(folder: str, products, stock, bom, end: date, days: int) -> None:
    out = HERE / folder
    _write(out / "products.csv", ["sku", "name", "type", "unit_cost", "unit", "category"],
           [p[:6] for p in products])
    first = end - timedelta(days=days)
    sales = []
    for i in range(days):
        d = first + timedelta(days=i)
        for sku, *_rest, per_day in products:
            if per_day:
                sales.append((d.isoformat(), sku, per_day, per_day * PRICE[sku]))
    _write(out / "sales.csv", ["date", "sku", "units", "revenue"], sales)
    _write(out / "inventory.csv", ["sku", "location", "on_hand", "inbound"],
           [(sku, "Main", qty, 0) for sku, qty in stock.items()])
    if bom:
        _write(out / "bom.csv", ["parent_sku", "component_sku", "qty_per_unit"], bom)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", type=date.fromisoformat, default=date.today(),
                    help="day the test runs; history ends the day before")
    ap.add_argument("--days", type=int, default=400)
    a = ap.parse_args()
    build("maker", MAKER_PRODUCTS, MAKER_STOCK, MAKER_BOM, a.end, a.days)
    build("reseller", RESELLER_PRODUCTS, RESELLER_STOCK, [], a.end, a.days)
    print(f"wrote maker/ and reseller/ with {a.days} days ending {a.end - timedelta(days=1)}")


if __name__ == "__main__":
    main()
