"""Pure planning math (no DB): stock projection, reorder points, order sizing.

Units: demand arrays are daily, index 0 = tomorrow (as_of + 1). Inbound is a dict
{day_index: qty} for open purchase orders expected on that day.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

# One-sided normal quantiles for common service levels; interpolated otherwise.
_Z_TABLE = {
    0.50: 0.0,
    0.80: 0.8416,
    0.85: 1.0364,
    0.90: 1.2816,
    0.95: 1.6449,
    0.975: 1.96,
    0.98: 2.0537,
    0.99: 2.3263,
    0.995: 2.5758,
    0.999: 3.0902,
}


def z_score(service_level: float) -> float:
    sl = min(max(float(service_level), 0.5), 0.999)
    keys = sorted(_Z_TABLE)
    for lo, hi in zip(keys, keys[1:], strict=False):
        if lo <= sl <= hi:
            t = (sl - lo) / (hi - lo)
            return _Z_TABLE[lo] + t * (_Z_TABLE[hi] - _Z_TABLE[lo])
    return _Z_TABLE[keys[-1]]


@dataclass
class Projection:
    stock: np.ndarray  # projected on-hand at END of each day (can go negative = unmet demand)
    stockout_day: int | None  # first day index with stock < 0 (None = none within horizon)
    days_of_cover: int | None  # days until stockout (None = beyond horizon)

    def stockout_date(self, as_of: date) -> date | None:
        return (
            as_of + timedelta(days=self.stockout_day + 1) if self.stockout_day is not None else None
        )


def project_stock(
    on_hand: float, demand: np.ndarray, inbound: dict[int, float] | None = None
) -> Projection:
    """Day-by-day: stock[d] = stock[d-1] + inbound[d] - demand[d]."""
    inbound = inbound or {}
    n = len(demand)
    stock = np.empty(n)
    level = float(on_hand)
    stockout: int | None = None
    for d in range(n):
        level += inbound.get(d, 0.0)
        level -= float(demand[d])
        stock[d] = level
        if stockout is None and level < 0:
            stockout = d
    cover = stockout if stockout is not None else None
    return Projection(stock, stockout, cover)


@dataclass
class ReorderPlan:
    daily_demand: float  # mean over the lead time
    sigma_daily: float
    safety_stock: float
    reorder_point: float
    order_day: int | None  # day index to place the order (0 = tomorrow; -1 = overdue/today)
    qty: float  # 0 = no order needed within horizon
    arrival_day: int | None


def reorder(
    on_hand: float,
    p50: np.ndarray,
    p90: np.ndarray,
    *,
    inbound: dict[int, float] | None,
    lead_time_days: int,
    service_level: float,
    target_cover_days: int,
    moq: float = 1.0,
    pack_size: float = 1.0,
) -> ReorderPlan:
    """Classic (s, Q) with forecast-derived uncertainty.

    sigma_daily comes from the forecast band (p90 - p50)/z90, so a confident forecast needs
    less safety stock than an uncertain one. The order is placed on the first day the stock
    position (on_hand + all inbound - demand so far) would fall below the reorder point.
    """
    L = max(int(lead_time_days), 0)
    n = len(p50)
    lt_window = p50[: max(L, 1)]
    daily = float(np.mean(lt_window)) if lt_window.size else 0.0
    sigma = (
        float(np.mean(np.maximum(p90[: max(L, 1)] - lt_window, 0) / 1.2816))
        if lt_window.size
        else 0.0
    )
    safety = z_score(service_level) * sigma * math.sqrt(max(L, 1))
    rop = daily * L + safety

    if daily <= 0 and on_hand >= 0:
        return ReorderPlan(daily, sigma, safety, rop, None, 0.0, None)

    inbound = inbound or {}
    # stock POSITION includes everything already ordered; find first breach of the ROP
    position = float(on_hand) + sum(inbound.values())
    order_day: int | None = None
    if position < rop:
        order_day = -1  # already below: order today
    else:
        for d in range(n):
            position -= float(p50[d])
            if position < rop:
                order_day = d
                break
    if order_day is None:
        return ReorderPlan(daily, sigma, safety, rop, None, 0.0, None)

    arrival = order_day + L
    # projected on-hand at arrival (inbound before arrival counts, demand until arrival consumed).
    # Lost-sales model: demand missed during a stockout is not back-ordered, so never below 0.
    proj = project_stock(on_hand, p50[: max(arrival + 1, 1)], inbound)
    at_arrival = (
        float(proj.stock[min(arrival, len(proj.stock) - 1)]) if arrival >= 0 else float(on_hand)
    )
    at_arrival = max(at_arrival, 0.0)
    cover_demand = float(np.sum(p50[max(arrival + 1, 0) : arrival + 1 + target_cover_days]))
    if cover_demand == 0 and daily > 0:
        cover_demand = daily * target_cover_days
    need = cover_demand + safety - at_arrival
    qty = max(need, float(moq))
    if pack_size and pack_size > 1:
        qty = math.ceil(qty / pack_size) * pack_size
    qty = float(math.ceil(qty))
    return ReorderPlan(daily, sigma, safety, rop, order_day, qty, arrival)


def health_status(
    *,
    on_hand: float,
    stockout_day: int | None,
    lead_time_days: int,
    at_risk_buffer_days: int,
    days_of_cover: int | None,
    overstock_days: int,
    daily_demand: float,
) -> str:
    if on_hand <= 0 and daily_demand > 0:
        return "stockout"
    if stockout_day is not None and stockout_day <= lead_time_days + at_risk_buffer_days:
        return "at_risk"
    if days_of_cover is None and daily_demand > 0 and on_hand > daily_demand * overstock_days:
        return "overstock"
    if days_of_cover is not None and days_of_cover > overstock_days:
        return "overstock"
    return "healthy"
