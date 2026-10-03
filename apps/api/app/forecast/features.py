"""Feature prep: org-level daily demand per SKU, gap-filled, with stockout days masked.

A "stockout day" is a day the product had on_hand == 0 at every location. Zero sales on
such a day say nothing about demand, so those points are excluded from training (set to
NaN) rather than treated as observed zeros.

Inventory history is not stored yet (only a current snapshot), so masking uses the current
snapshot for the trailing window: if on_hand is 0 now, the most recent run of zero-sales
days is assumed to be a stockout. When inventory snapshots get a history table, swap
`stockout_days()` for a real per-day lookup; the rest of the pipeline is unchanged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BomLine, InventoryLevel, Product, ProductType, SalesDaily


@dataclass(eq=False)  # identity-hashable: used as dict keys in the router
class Series:
    product_id: uuid.UUID
    sku: str
    category_id: uuid.UUID | None
    dates: pd.DatetimeIndex
    y: np.ndarray  # float, NaN where masked
    stockout_mask: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))

    @property
    def history_days(self) -> int:
        """Observed (non-masked) days."""
        return int(np.count_nonzero(~np.isnan(self.y)))

    @property
    def zero_share(self) -> float:
        obs = self.y[~np.isnan(self.y)]
        return float(np.mean(obs == 0)) if obs.size else 1.0

    @property
    def observed(self) -> np.ndarray:
        return self.y[~np.isnan(self.y)]


def load_series(
    db: Session,
    org_id: uuid.UUID,
    *,
    as_of: date,
    lookback_days: int = 730,
    product_ids: list[uuid.UUID] | None = None,
) -> list[Series]:
    """One Series per sellable product (finished + bundle), summed across channels."""
    start = as_of - timedelta(days=lookback_days - 1)
    prod_q = select(Product.id, Product.sku, Product.category_id).where(
        Product.org_id == org_id,
        Product.is_active.is_(True),
        Product.type.in_([ProductType.finished, ProductType.bundle]),
    )
    if product_ids:
        prod_q = prod_q.where(Product.id.in_(product_ids))
    products = {pid: (sku, cat) for pid, sku, cat in db.execute(prod_q)}
    if not products:
        return []

    sales_q = (
        select(SalesDaily.product_id, SalesDaily.date, func.sum(SalesDaily.units))
        .where(
            SalesDaily.org_id == org_id,
            SalesDaily.product_id.in_(list(products)),
            SalesDaily.date.between(start, as_of),
        )
        .group_by(SalesDaily.product_id, SalesDaily.date)
    )
    rows = db.execute(sales_q).all()
    sales = (
        pd.DataFrame(rows, columns=["product_id", "date", "units"])
        if rows
        else pd.DataFrame(columns=["product_id", "date", "units"])
    )
    sales["units"] = sales["units"].astype(float)

    stock = {
        pid: float(total or 0)
        for pid, total in db.execute(
            select(InventoryLevel.product_id, func.sum(InventoryLevel.on_hand))
            .where(InventoryLevel.org_id == org_id, InventoryLevel.product_id.in_(list(products)))
            .group_by(InventoryLevel.product_id)
        )
    }

    idx = pd.date_range(start, as_of, freq="D")
    raw_y: dict[uuid.UUID, np.ndarray] = {}
    for pid in products:
        s = sales[sales["product_id"] == pid].set_index("date")["units"]
        s.index = pd.to_datetime(s.index)
        raw_y[pid] = s.reindex(idx, fill_value=0.0).to_numpy(dtype=float)

    # Bundles: their sales are demand for their components, not for the bundle itself.
    # Decompose before forecasting; the bundle SKU is then planned as derived demand.
    bundle_ids = [pid for pid, (_, _) in products.items() if _is_bundle(db, pid)]
    if bundle_ids:
        lines = db.execute(
            select(
                BomLine.parent_product_id, BomLine.component_product_id, BomLine.qty_per_unit
            ).where(BomLine.org_id == org_id, BomLine.parent_product_id.in_(bundle_ids))
        ).all()
        for parent, comp, per in lines:
            if comp in raw_y:
                raw_y[comp] = raw_y[comp] + raw_y[parent] * float(per)
            elif comp in products:
                raw_y[comp] = raw_y[parent] * float(per)
        for b in bundle_ids:
            raw_y.pop(b, None)

    out: list[Series] = []
    for pid, y in raw_y.items():
        sku, cat = products[pid]
        first = _first_sale_index(y)
        if first is None:
            continue  # never sold: nothing to learn, planning treats it as new
        y = y[first:]
        dates = idx[first:]
        mask = stockout_days(y, on_hand_now=stock.get(pid, 0.0)) | sync_lag_days(y)
        y_masked = y.copy()
        y_masked[mask] = np.nan
        out.append(Series(pid, sku, cat, dates, y_masked, mask))
    return out


_BUNDLE_CACHE_KEY = "_stockcast_bundle_types"


def _is_bundle(db: Session, pid: uuid.UUID) -> bool:
    cache = db.info.setdefault(_BUNDLE_CACHE_KEY, {})
    if pid not in cache:
        cache[pid] = db.scalar(select(Product.type).where(Product.id == pid)) == ProductType.bundle
    return cache[pid]


def stockout_days(y: np.ndarray, *, on_hand_now: float, min_run: int = 2) -> np.ndarray:
    """Mask the trailing run of zero-sales days when the product is out of stock now.

    Requires at least `min_run` consecutive zeros so a single quiet day is not mislabelled.
    """
    mask = np.zeros(len(y), dtype=bool)
    if on_hand_now > 0 or len(y) == 0:
        return mask
    i = len(y) - 1
    while i >= 0 and y[i] == 0:
        i -= 1
    run = len(y) - 1 - i
    if run >= min_run:
        mask[i + 1 :] = True
    return mask


def sync_lag_days(y: np.ndarray, *, max_lag: int = 3, lookback: int = 14) -> np.ndarray:
    """Mask a short trailing run of zeros after steady sales: the channel has not synced yet.

    One unsynced day at the end of a series is enough to make an ETS model collapse toward
    zero, so those days are treated as unobserved rather than as real zero demand.
    """
    mask = np.zeros(len(y), dtype=bool)
    if len(y) <= lookback + max_lag:
        return mask
    i = len(y) - 1
    while i >= 0 and y[i] == 0:
        i -= 1
    run = len(y) - 1 - i
    if 0 < run <= max_lag and np.nanmean(y[max(0, i - lookback + 1) : i + 1]) > 0:
        mask[i + 1 :] = True
    return mask


def _first_sale_index(y: np.ndarray) -> int | None:
    nz = np.flatnonzero(y > 0)
    return int(nz[0]) if nz.size else None
