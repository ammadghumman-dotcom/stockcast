"""CSV connector: parses uploaded files with an optional column mapping into records.

Default column names (case-insensitive, extra columns ignored):
  products.csv   sku, name, type, unit_cost, unit, category
  sales.csv      date, sku, units, revenue
  inventory.csv  sku, location, on_hand, inbound
  bom.csv        parent_sku, component_sku, qty_per_unit

A mapping {"target_field": "Source Column"} renames source headers to the fields above.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator
from datetime import date
from typing import Any

from pydantic import BaseModel, ValidationError

from app.ingest.base import BaseConnector
from app.ingest.records import (
    BomRecord,
    InventoryRecord,
    ProductRecord,
    RowError,
    SalesRecord,
)

KINDS: dict[str, tuple[type[BaseModel], tuple[str, ...]]] = {
    "products": (ProductRecord, ("sku", "name")),
    "sales": (SalesRecord, ("date", "sku", "units")),
    "inventory": (InventoryRecord, ("sku", "location", "on_hand")),
    "bom": (BomRecord, ("parent_sku", "component_sku", "qty_per_unit")),
}

MAX_ROWS = 200_000


class CsvParseError(ValueError):
    pass


def parse_csv(
    kind: str, data: bytes, mapping: dict[str, str] | None = None
) -> tuple[list[BaseModel], list[RowError]]:
    """Return (valid records, row errors). Never raises on a bad row — only on a bad file."""
    if kind not in KINDS:
        raise CsvParseError(f"unknown kind {kind!r}; expected one of {sorted(KINDS)}")
    model, required = KINDS[kind]
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvParseError("file is not UTF-8") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise CsvParseError("empty file or missing header row")

    # Build header -> field map: apply user mapping first, then case-insensitive defaults.
    mapping = {k.strip(): v.strip() for k, v in (mapping or {}).items()}
    header_to_field: dict[str, str] = {}
    lower_headers = {h.strip().lower(): h for h in reader.fieldnames if h}
    for field in model.model_fields:
        src = mapping.get(field)
        if src and src in reader.fieldnames:
            header_to_field[src] = field
        elif field in lower_headers:
            header_to_field[lower_headers[field]] = field
    missing = [f for f in required if f not in header_to_field.values()]
    if missing:
        raise CsvParseError(
            f"missing required column(s) {missing}; headers were {reader.fieldnames}"
        )

    records: list[BaseModel] = []
    errors: list[RowError] = []
    for row_no, raw in enumerate(reader, start=1):
        if row_no > MAX_ROWS:
            errors.append(RowError(row=row_no, message=f"more than {MAX_ROWS} rows; truncated"))
            break
        payload: dict[str, Any] = {}
        for header, field in header_to_field.items():
            val = (raw.get(header) or "").strip()
            if val != "":
                payload[field] = val
        if not any(payload.values()):
            continue  # blank line
        try:
            records.append(model.model_validate(payload))
        except ValidationError as exc:
            msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            errors.append(RowError(row=row_no, message=msg))
    return records, errors


def to_csv(kind: str, rows: Iterable[BaseModel]) -> str:
    model, _ = KINDS[kind]
    fields = [f for f in model.model_fields if f not in ("external_id", "external_sku")]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    for r in rows:
        d = r.model_dump(mode="json")
        w.writerow({k: ("" if d.get(k) is None else d[k]) for k in fields})
    return buf.getvalue()


class CsvConnector(BaseConnector):
    """Holds files handed to it by the upload endpoint; `fetch_*` replay them as records."""

    def __init__(self, channel, files: dict[str, bytes] | None = None, mapping=None) -> None:
        super().__init__(channel)
        self.files = files or {}
        self.mapping: dict[str, dict[str, str]] = mapping or {}
        self.errors: dict[str, list[RowError]] = {}

    def _records(self, kind: str) -> Iterator[Any]:
        data = self.files.get(kind)
        if data is None:
            return iter(())
        records, errors = parse_csv(kind, data, self.mapping.get(kind))
        self.errors[kind] = errors
        return iter(records)

    def fetch_products(self) -> Iterable[ProductRecord]:
        return self._records("products")

    def fetch_sales(self, since: date) -> Iterable[SalesRecord]:
        return (r for r in self._records("sales") if r.date >= since)

    def fetch_inventory(self) -> Iterable[InventoryRecord]:
        return self._records("inventory")

    def fetch_bom(self) -> Iterable[BomRecord]:
        return self._records("bom")
