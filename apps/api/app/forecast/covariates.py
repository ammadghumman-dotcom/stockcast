"""Demand covariates: holiday/event uplift per (region, category) and promotion lift.

Pipeline position
-----------------
`build_factors()` turns events + promotions into one multiplicative factor per product per
day (history and horizon). The engine DIVIDES history by the factor before modelling and
MULTIPLIES the base forecast by it afterwards, so the base model sees de-seasonalised
demand and every uplift is explicit, inspectable and explainable.

Learning
--------
* Holiday uplift per (region, category, event name): for each past occurrence, counterfactual
  baseline = base model trained on history before the window (the window is masked), ratio =
  actual / baseline, aggregated over all products in the category weighted by volume.
  Stored in `category_holiday_uplift` with `learned=True, sample_size=n`; categories without
  history keep editable priors (`learned=False`).
* Promotion lift per promotion: actual / counterfactual over the promo window, plus the dip
  in the 7 days after. Then ridge regression log(lift) ~ discount_pct + log1p(spend) + type +
  channel + category per org (>= 3 observations) with a global fallback.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.forecast.features import Series
from app.forecast.models import StatsModel, chronos_available, chronos_predict_batch
from app.models import (
    CategoryHolidayUplift,
    Channel,
    HolidayEvent,
    Product,
    ProductCategory,
    PromoLiftModel,
    Promotion,
    Region,
    SalesDaily,
)
from app.models.enums import PromotionScope, PromotionType

POST_PROMO_DAYS = 7
MIN_PROMO_SAMPLES = 3
SHRINK_DAYS = 5  # uplift shrinkage: w = observed_days / (observed_days + SHRINK_DAYS)
PRIOR_BAND_WIDEN = 1.5  # widen p10/p90 by this when a factor comes from a prior, not data

# --------------------------------------------------------------------------- priors
# Editable defaults by category keyword x event. Values are multipliers (2.5 = +150 %).
CATEGORY_PRIORS: dict[str, dict[str, float]] = {
    "candle": {"Christmas": 2.5, "Black Friday": 1.8, "Valentine's Day": 1.5, "Mother's Day": 1.6},
    "gift": {"Christmas": 2.5, "Black Friday": 2.0, "Valentine's Day": 1.8, "Mother's Day": 1.9},
    "beauty": {"Christmas": 1.8, "Black Friday": 1.7, "Mother's Day": 1.8, "Valentine's Day": 1.4},
    "perfume": {
        "Christmas": 1.8,
        "Black Friday": 1.7,
        "Mother's Day": 1.6,
        "Ramadan/Eid": 1.8,
        "Valentine's Day": 1.5,
    },
    "fragrance": {"Christmas": 1.8, "Black Friday": 1.7, "Ramadan/Eid": 1.8},
    "apparel": {"Christmas": 1.6, "Black Friday": 2.0, "Cyber Monday": 1.6},
    "electronics": {"Black Friday": 2.4, "Cyber Monday": 2.2, "Prime Day": 2.0, "Christmas": 1.5},
    "toy": {"Christmas": 3.0, "Black Friday": 2.0},
    "food": {"Christmas": 1.6, "Ramadan/Eid": 1.5, "Diwali": 1.4},
}
GENERIC_PRIOR = {
    "Christmas": 1.4,
    "Black Friday": 1.5,
    "Cyber Monday": 1.3,
    "Prime Day": 1.2,
    "Singles Day": 1.1,
    "Valentine's Day": 1.1,
    "Mother's Day": 1.1,
    "Ramadan/Eid": 1.2,
    "Diwali": 1.2,
}

# Global promo model used until an org has >= MIN_PROMO_SAMPLES observed promotions.
# log(lift) = b0 + b_disc*discount_pct + b_spend*log1p(spend) + type effects
GLOBAL_COEF: dict[str, float] = {
    "intercept": 0.05,
    "discount_pct": 0.022,
    "log_spend": 0.03,
    "type:paid_ads": 0.0,
    "type:discount": 0.05,
    "type:email": -0.05,
}
GLOBAL_POST_DIP = 0.85


def prior_multiplier(category_name: str | None, event_name: str) -> float:
    low = (category_name or "").lower()
    for key, table in CATEGORY_PRIORS.items():
        if key in low and event_name in table:
            return table[event_name]
    return GENERIC_PRIOR.get(event_name, 1.0)


# --------------------------------------------------------------------------- data shapes
@dataclass
class EventOcc:
    name: str
    region_id: uuid.UUID
    start: date
    end: date


@dataclass
class Uplift:
    multiplier: float
    learned: bool
    sample_size: int = 0


@dataclass
class Factors:
    """Per-product daily multipliers over [hist_start .. as_of + horizon]."""

    product_id: uuid.UUID
    dates: list[date]
    factor: np.ndarray
    from_prior: np.ndarray  # bool: factor on this date rests on a prior, not learned data
    event: list[str | None] = field(default_factory=list)

    def split(self, as_of: date) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str | None]]:
        cut = self.dates.index(as_of) + 1 if as_of in self.dates else len(self.dates)
        return self.factor[:cut], self.factor[cut:], self.from_prior[cut:], self.event[cut:]


# --------------------------------------------------------------------------- loading
def load_events(db: Session, org_id: uuid.UUID, start: date, end: date) -> list[EventOcc]:
    rows = db.scalars(
        select(HolidayEvent).where(
            HolidayEvent.org_id == org_id,
            HolidayEvent.end_date >= start,
            HolidayEvent.start_date <= end,
        )
    ).all()
    return [EventOcc(e.name, e.region_id, e.start_date, e.end_date) for e in rows]


def load_region_shares(
    db: Session, org_id: uuid.UUID, as_of: date
) -> dict[uuid.UUID, dict[uuid.UUID, float]]:
    """product_id -> {region_id: share of units in the last 365 days}. Missing region = org's
    largest region."""
    rows = db.execute(
        select(SalesDaily.product_id, Channel.region_id, func.sum(SalesDaily.units))
        .join(Channel, Channel.id == SalesDaily.channel_id)
        .where(SalesDaily.org_id == org_id, SalesDaily.date > as_of - timedelta(days=365))
        .group_by(SalesDaily.product_id, Channel.region_id)
    ).all()
    tot: dict[uuid.UUID, float] = defaultdict(float)
    per: dict[uuid.UUID, dict[uuid.UUID, float]] = defaultdict(dict)
    org_tot: dict[uuid.UUID, float] = defaultdict(float)
    for pid, rid, units in rows:
        if rid is None:
            continue
        u = float(units or 0)
        per[pid][rid] = per[pid].get(rid, 0.0) + u
        tot[pid] += u
        org_tot[rid] += u
    out = {pid: {r: u / tot[pid] for r, u in d.items() if tot[pid] > 0} for pid, d in per.items()}
    if org_tot:
        top = max(org_tot, key=org_tot.get)
        out.setdefault("__default__", {top: 1.0})  # type: ignore[arg-type]
    return out


def load_uplifts(db: Session, org_id: uuid.UUID) -> dict[tuple, Uplift]:
    """(category_id, region_id, event_name) -> Uplift (learned or stored prior)."""
    return {
        (u.category_id, u.region_id, u.event_name): Uplift(
            1.0 + float(u.uplift_pct) / 100.0, u.learned, u.sample_size or 0
        )
        for u in db.scalars(
            select(CategoryHolidayUplift).where(CategoryHolidayUplift.org_id == org_id)
        )
    }


# --------------------------------------------------------------------------- factors
def build_factors(
    series: list[Series],
    *,
    as_of: date,
    horizon: int,
    events: list[EventOcc],
    uplifts: dict[tuple, Uplift],
    category_names: dict[uuid.UUID, str],
    region_shares: dict,
    promotions: list[Promotion],
    promo_coef: dict[str, float],
    post_dip: float,
    channel_region: dict[uuid.UUID, uuid.UUID | None],
) -> dict[uuid.UUID, Factors]:
    out: dict[uuid.UUID, Factors] = {}
    default_share = region_shares.get("__default__", {})
    for s in series:
        hist_start = s.dates[0].date()
        dates = [
            hist_start + timedelta(days=i) for i in range((as_of - hist_start).days + 1 + horizon)
        ]
        n = len(dates)
        factor = np.ones(n)
        from_prior = np.zeros(n, dtype=bool)
        event_on: list[str | None] = [None] * n
        shares = region_shares.get(s.product_id) or default_share
        cat_name = category_names.get(s.category_id) if s.category_id else None

        # holiday / event uplift: share-weighted across the product's sales regions.
        # Overlapping events (Christmas ⊃ Black Friday ⊃ Cyber Monday) each describe the TOTAL
        # uplift of their window, so per day the dominant (max) factor wins; never multiplied.
        ev_factor = np.ones(n)
        ev_prior = np.zeros(n, dtype=bool)
        for ev in events:
            share = shares.get(ev.region_id, 0.0)
            if share <= 0:
                continue
            up = uplifts.get((s.category_id, ev.region_id, ev.name))
            if up is None:
                up = Uplift(prior_multiplier(cat_name, ev.name), learned=False)
            if abs(up.multiplier - 1.0) < 1e-6:
                continue
            i0 = max(0, (ev.start - hist_start).days)
            i1 = min(n - 1, (ev.end - hist_start).days)
            if i1 < i0:
                continue
            full_len = (ev.end - ev.start).days + 1
            ramp = np.linspace(0.4, 1.0, full_len)
            ramp = ramp / ramp.mean()  # learned ratio is the window MEAN; keep it so
            off = i0 - (ev.start - hist_start).days
            seg = ramp[off : off + (i1 - i0 + 1)]
            mult = 1.0 + (up.multiplier - 1.0) * seg * share
            better = mult > ev_factor[i0 : i1 + 1]
            ev_factor[i0 : i1 + 1] = np.where(better, mult, ev_factor[i0 : i1 + 1])
            idx = np.flatnonzero(better) + i0
            ev_prior[idx] = not up.learned
            for i in idx:
                event_on[i] = ev.name
        factor *= ev_factor
        from_prior |= ev_prior

        # promotions: observed lift in history, predicted lift for upcoming/active
        for p in promotions:
            if not promo_applies(p, s):
                continue
            lift = (
                float(p.observed_lift) if p.observed_lift else predict_lift(p, promo_coef, cat_name)
            )
            dip = float(p.observed_post_dip) if p.observed_post_dip else post_dip
            i0 = max(0, (p.start_date - hist_start).days)
            i1 = min(n - 1, (p.end_date - hist_start).days)
            if i1 >= i0:
                factor[i0 : i1 + 1] *= lift
                if p.observed_lift is None:
                    from_prior[i0 : i1 + 1] = True
                for i in range(i0, i1 + 1):
                    event_on[i] = f"promo: {p.name}"
            d0, d1 = i1 + 1, min(n - 1, i1 + POST_PROMO_DAYS)
            if d1 >= d0 and dip != 1.0:
                factor[d0 : d1 + 1] *= dip
        out[s.product_id] = Factors(s.product_id, dates, factor, from_prior, event_on)
    return out


def promo_applies(p: Promotion, s: Series) -> bool:
    if p.scope == PromotionScope.all:
        return True
    if p.scope == PromotionScope.category:
        return p.category_id is not None and p.category_id == s.category_id
    return str(s.product_id) in (p.product_ids or [])


def predict_lift(p: Promotion, coef: dict[str, float], category_name: str | None) -> float:
    x = coef.get("intercept", 0.0)
    x += coef.get("discount_pct", 0.0) * float(p.discount_pct or 0)
    x += coef.get("log_spend", 0.0) * math.log1p(float(p.spend_amount or 0))
    x += coef.get(f"type:{p.type.value}", 0.0)
    if p.channel_id:
        x += coef.get(f"channel:{p.channel_id}", 0.0)
    if category_name:
        x += coef.get(f"category:{category_name.lower()}", 0.0)
    return float(np.clip(math.exp(x), 0.5, 10.0))


# --------------------------------------------------------------------------- learning
def _baseline_batch(contexts: list[np.ndarray], h: int) -> list[np.ndarray]:
    """Counterfactual p50 over `h` days from the history before the window."""
    if chronos_available():
        return [b.p50 for b in chronos_predict_batch(contexts, h)]
    return [b.p50 for b in StatsModel.predict_batch(contexts, h)]


def learn_holiday_uplifts(
    series: list[Series],
    events: list[EventOcc],
    *,
    region_shares: dict,
    cutoff: date,
    min_history: int = 56,
) -> dict[tuple, Uplift]:
    """(category_id, region_id, event_name) -> learned Uplift from occurrences ending < cutoff.

    Products are attributed to a region by their sales share, so an event in region R only
    contributes for products that actually sell there (weighted by that share).
    """
    jobs: list[tuple[Series, EventOcc, np.ndarray, int]] = []
    default_share = region_shares.get("__default__", {})
    for s in series:
        if s.category_id is None:
            continue
        shares = region_shares.get(s.product_id) or default_share
        hist_start = s.dates[0].date()
        for ev in events:
            if ev.end >= cutoff or shares.get(ev.region_id, 0.0) <= 0:
                continue
            i0, i1 = (ev.start - hist_start).days, (ev.end - hist_start).days
            if i0 < min_history or i1 >= len(s.y):
                continue
            train = s.y[:i0]
            if np.count_nonzero(~np.isnan(train)) < min_history:
                continue
            jobs.append((s, ev, train, i1 - i0 + 1))
    if not jobs:
        return {}

    by_h: dict[int, list[int]] = defaultdict(list)
    for i, (_, _, _, h) in enumerate(jobs):
        by_h[h].append(i)
    baseline: dict[int, np.ndarray] = {}
    for h, idxs in by_h.items():
        for i, p50 in zip(idxs, _baseline_batch([jobs[i][2] for i in idxs], h), strict=True):
            baseline[i] = p50

    acc: dict[tuple, list[float]] = defaultdict(lambda: [0.0, 0.0, 0, 0])  # actual, base, n, days
    for i, (s, ev, _, h) in enumerate(jobs):
        hist_start = s.dates[0].date()
        i0 = (ev.start - hist_start).days
        actual = s.y[i0 : i0 + h]
        obs = ~np.isnan(actual)
        if obs.sum() < max(3, h // 3):
            continue
        base = baseline[i][obs]
        share = (region_shares.get(s.product_id) or default_share).get(ev.region_id, 1.0)
        key = (s.category_id, ev.region_id, ev.name)
        acc[key][0] += float(actual[obs].sum()) * share
        acc[key][1] += float(base.sum()) * share
        acc[key][2] += 1
        acc[key][3] += int(obs.sum())
    out: dict[tuple, Uplift] = {}
    for key, (a, b, n, days) in acc.items():
        if b <= 0 or n == 0:
            continue
        ratio = float(np.clip(a / b, 0.3, 8.0))
        # shrink toward 1 when the evidence is thin (few observed window-days)
        w = days / (days + SHRINK_DAYS)
        out[key] = Uplift(1.0 + (ratio - 1.0) * w, learned=True, sample_size=n)
    return out


def persist_uplifts(
    db: Session,
    org_id: uuid.UUID,
    learned: dict[tuple, Uplift],
    *,
    cat_ids: set[uuid.UUID],
    regions: list[uuid.UUID],
    event_names: set[str],
    category_names: dict[uuid.UUID, str],
) -> None:
    """Upsert learned rows; add prior rows for (category, region, event) combos not yet stored
    so users can see and edit them."""
    existing = {
        (u.category_id, u.region_id, u.event_name): u
        for u in db.scalars(
            select(CategoryHolidayUplift).where(CategoryHolidayUplift.org_id == org_id)
        )
    }
    for key, up in learned.items():
        row = existing.get(key)
        pct = Decimal(f"{(up.multiplier - 1) * 100:.2f}")
        if row is None:
            row = CategoryHolidayUplift(
                org_id=org_id,
                category_id=key[0],
                region_id=key[1],
                event_name=key[2],
                uplift_pct=pct,
                learned=True,
                sample_size=up.sample_size,
            )
            db.add(row)
            existing[key] = row
        else:
            row.uplift_pct, row.learned, row.sample_size = pct, True, up.sample_size
    for cid in cat_ids:
        for rid in regions:
            for name in event_names:
                key = (cid, rid, name)
                if key in existing:
                    continue
                m = prior_multiplier(category_names.get(cid), name)
                if abs(m - 1.0) < 1e-9:
                    continue
                row = CategoryHolidayUplift(
                    org_id=org_id,
                    category_id=cid,
                    region_id=rid,
                    event_name=name,
                    uplift_pct=Decimal(f"{(m - 1) * 100:.2f}"),
                    learned=False,
                    sample_size=0,
                )
                db.add(row)
                existing[key] = row
    db.flush()


# --------------------------------------------------------------------------- promotions
def measure_promotions(
    series: list[Series], promotions: list[Promotion], *, cutoff: date
) -> dict[uuid.UUID, tuple[float, float, float]]:
    """promotion_id -> (lift, post_dip, baseline_units) for promotions that ended before cutoff."""
    jobs: list[tuple[Promotion, Series, np.ndarray, int]] = []
    for p in promotions:
        if p.end_date >= cutoff:
            continue
        for s in series:
            if not promo_applies(p, s):
                continue
            hist_start = s.dates[0].date()
            i0 = (p.start_date - hist_start).days
            i1 = (p.end_date - hist_start).days + POST_PROMO_DAYS
            if i0 < 28 or i1 >= len(s.y):
                continue
            jobs.append((p, s, s.y[:i0], i1 - i0 + 1))
    if not jobs:
        return {}
    by_h: dict[int, list[int]] = defaultdict(list)
    for i, (_, _, _, h) in enumerate(jobs):
        by_h[h].append(i)
    base: dict[int, np.ndarray] = {}
    for h, idxs in by_h.items():
        for i, p50 in zip(idxs, _baseline_batch([jobs[i][2] for i in idxs], h), strict=True):
            base[i] = p50
    acc: dict[uuid.UUID, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for i, (p, s, _, h) in enumerate(jobs):
        hist_start = s.dates[0].date()
        i0 = (p.start_date - hist_start).days
        win = (p.end_date - p.start_date).days + 1
        actual = np.nan_to_num(s.y[i0 : i0 + h])
        b = np.maximum(base[i], 1e-6)
        acc[p.id][0] += float(actual[:win].sum())
        acc[p.id][1] += float(b[:win].sum())
        acc[p.id][2] += float(actual[win:].sum())
        acc[p.id][3] += float(b[win:].sum())
    out = {}
    for pid, (a, b, a2, b2) in acc.items():
        if b <= 0:
            continue
        lift = float(np.clip(a / b, 0.5, 10.0))
        dip = float(np.clip(a2 / b2, 0.3, 1.5)) if b2 > 0 else GLOBAL_POST_DIP
        out[pid] = (lift, dip, b)
    return out


def fit_promo_model(
    promotions: list[Promotion], category_names: dict[uuid.UUID, str], *, alpha: float = 1.0
) -> tuple[dict[str, float], float, int, float | None] | None:
    """Ridge on log(observed_lift). Returns (coef, post_dip, n, r2) or None if too few samples."""
    obs = [p for p in promotions if p.observed_lift is not None]
    if len(obs) < MIN_PROMO_SAMPLES:
        return None
    feats: list[str] = ["discount_pct", "log_spend"]
    for p in obs:
        feats.append(f"type:{p.type.value}")
        if p.channel_id:
            feats.append(f"channel:{p.channel_id}")
        if p.category_id and p.category_id in category_names:
            feats.append(f"category:{category_names[p.category_id].lower()}")
    feats = sorted(set(feats))
    col = {f: i for i, f in enumerate(feats)}
    X = np.zeros((len(obs), len(feats)))
    y = np.zeros(len(obs))
    for r, p in enumerate(obs):
        X[r, col["discount_pct"]] = float(p.discount_pct or 0)
        X[r, col["log_spend"]] = math.log1p(float(p.spend_amount or 0))
        X[r, col[f"type:{p.type.value}"]] = 1.0
        if p.channel_id:
            X[r, col[f"channel:{p.channel_id}"]] = 1.0
        if p.category_id and p.category_id in category_names:
            X[r, col[f"category:{category_names[p.category_id].lower()}"]] = 1.0
        y[r] = math.log(float(p.observed_lift))
    mu = y.mean()
    yc = y - mu
    # ridge, no penalty on intercept (handled by centering)
    A = X.T @ X + alpha * np.eye(len(feats))
    beta = np.linalg.solve(A, X.T @ yc)
    pred = X @ beta + mu
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - mu) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None
    coef = {"intercept": float(mu - (X.mean(axis=0) @ beta))}
    coef.update({f: float(beta[i]) for f, i in col.items()})
    dips = [float(p.observed_post_dip) for p in obs if p.observed_post_dip is not None]
    post_dip = float(np.mean(dips)) if dips else GLOBAL_POST_DIP
    return coef, post_dip, len(obs), r2


def load_promo_model(db: Session, org_id: uuid.UUID) -> tuple[dict[str, float], float]:
    row = db.scalar(select(PromoLiftModel).where(PromoLiftModel.org_id == org_id))
    if row is None:
        return dict(GLOBAL_COEF), GLOBAL_POST_DIP
    return dict(row.coef), float(row.post_dip)


def save_promo_model(
    db: Session, org_id: uuid.UUID, coef: dict, post_dip: float, n: int, r2: float | None
) -> None:
    row = db.scalar(select(PromoLiftModel).where(PromoLiftModel.org_id == org_id))
    if row is None:
        row = PromoLiftModel(
            org_id=org_id, coef=coef, n_samples=n, post_dip=Decimal(f"{post_dip:.4f}")
        )
        db.add(row)
    else:
        row.coef, row.n_samples, row.post_dip = coef, n, Decimal(f"{post_dip:.4f}")
    row.r2 = Decimal(f"{r2:.4f}") if r2 is not None else None
    db.flush()


# --------------------------------------------------------------------------- helpers
def category_name_map(db: Session, org_id: uuid.UUID) -> dict[uuid.UUID, str]:
    return dict(
        db.execute(
            select(ProductCategory.id, ProductCategory.name).where(ProductCategory.org_id == org_id)
        ).all()
    )


def org_regions(db: Session, org_id: uuid.UUID) -> list[uuid.UUID]:
    return list(db.scalars(select(Region.id).where(Region.org_id == org_id)).all())


def channel_region_map(db: Session, org_id: uuid.UUID) -> dict[uuid.UUID, uuid.UUID | None]:
    rows = db.execute(select(Channel.id, Channel.region_id).where(Channel.org_id == org_id))
    return {cid: rid for cid, rid in rows}


def load_promotions(db: Session, org_id: uuid.UUID, start: date, end: date) -> list[Promotion]:
    return list(
        db.scalars(
            select(Promotion).where(
                Promotion.org_id == org_id, Promotion.end_date >= start, Promotion.start_date <= end
            )
        ).all()
    )


__all__ = [
    "GLOBAL_COEF",
    "PRIOR_BAND_WIDEN",
    "EventOcc",
    "Factors",
    "Uplift",
    "build_factors",
    "category_name_map",
    "channel_region_map",
    "fit_promo_model",
    "learn_holiday_uplifts",
    "load_events",
    "load_promo_model",
    "load_promotions",
    "load_region_shares",
    "load_uplifts",
    "measure_promotions",
    "org_regions",
    "persist_uplifts",
    "predict_lift",
    "prior_multiplier",
    "promo_applies",
    "save_promo_model",
    "Product",
    "PromotionType",
]
