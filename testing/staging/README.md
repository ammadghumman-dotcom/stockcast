# Staging test data

Data and expected results for the staging test round. The plan and the cases live in the
"Stockcast — Staging Test Plan" and "Stockcast — Staging Test Cases" docs.

| File | What it is |
| --- | --- |
| `make_data.py` | Writes the CSVs. Run on the test day: `python testing/staging/make_data.py --end YYYY-MM-DD` (history ends the day before). Standard library only. |
| `maker/` | QA Candle Co: 3 candles, 3 raw materials, 9 BOM lines, 400 days of flat sales, stock. |
| `reseller/` | QA Gift Shop: 4 bought products, no BOM, 400 days of flat sales, stock. |
| `build_expected.py` | Replays the setup through the API against a local scratch database and writes `expected_results.json` (see its docstring). |
| `expected_results.json` | Every recommendation for both workspaces, generated for 2026-10-08 with AutoETS. |

Every product sells the same number of units every day, so forecasts are flat and the planning
numbers can be checked by hand: reorder point = daily demand × lead time (safety stock 0), order
quantity = 30 days of cover raised to the supplier's MOQ, raw-material demand = Σ parent demand ×
quantity per unit. On staging (which also runs Chronos) allow ±2 % on demand and quantities and
±1 day on dates; dates are relative to the test day.

Known gaps found while building this (expected failures):
- No API or screen sets a supplier's item price, pack size or per-item lead time (FR-CAT-6).
- A BOM line that creates a loop is accepted (FR-CAT-7); planning still completes.
