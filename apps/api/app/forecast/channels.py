"""Per-channel demand split: share of each product's units over the trailing window."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import ForecastChannelShare, SalesDaily

WINDOW_DAYS = 90


def compute_channel_shares(
    db: Session,
    org_id: uuid.UUID,
    run_id: uuid.UUID,
    as_of: date,
    *,
    product_ids: list[uuid.UUID] | None = None,
    window_days: int = WINDOW_DAYS,
) -> int:
    """Replace this run's rows with shares from the last `window_days` of sales. Returns rows."""
    start = as_of - timedelta(days=window_days - 1)
    q = (
        select(SalesDaily.product_id, SalesDaily.channel_id, func.sum(SalesDaily.units))
        .where(SalesDaily.org_id == org_id, SalesDaily.date >= start, SalesDaily.date <= as_of)
        .group_by(SalesDaily.product_id, SalesDaily.channel_id)
    )
    if product_ids:
        q = q.where(SalesDaily.product_id.in_(product_ids))
    totals: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    rows = db.execute(q).all()
    for pid, _cid, units in rows:
        totals[pid] += Decimal(units or 0)
    db.execute(delete(ForecastChannelShare).where(ForecastChannelShare.run_id == run_id))
    out = []
    for pid, cid, units in rows:
        units = Decimal(units or 0)
        if totals[pid] <= 0:
            continue
        out.append(
            {
                "id": uuid.uuid4(),
                "org_id": org_id,
                "run_id": run_id,
                "product_id": pid,
                "channel_id": cid,
                "share": (units / totals[pid]).quantize(Decimal("0.0001")),
                "units_90d": units,
            }
        )
    if out:
        db.bulk_insert_mappings(ForecastChannelShare, out)
    return len(out)


def load_channel_mix(
    db: Session, org_id: uuid.UUID, run_id: uuid.UUID, product_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[dict]]:
    """product_id -> [{channel_id, channel_name, channel_type, share, units_90d}], by share."""
    from app.models import Channel

    if not product_ids:
        return {}
    rows = db.execute(
        select(ForecastChannelShare, Channel.name, Channel.type)
        .join(Channel, Channel.id == ForecastChannelShare.channel_id)
        .where(
            ForecastChannelShare.org_id == org_id,
            ForecastChannelShare.run_id == run_id,
            ForecastChannelShare.product_id.in_(product_ids),
        )
        .order_by(ForecastChannelShare.share.desc())
    ).all()
    out: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for cs, name, ctype in rows:
        out[cs.product_id].append(
            {
                "channel_id": cs.channel_id,
                "channel_name": name,
                "channel_type": ctype.value,
                "share": cs.share,
                "units_90d": cs.units_90d,
            }
        )
    return out
