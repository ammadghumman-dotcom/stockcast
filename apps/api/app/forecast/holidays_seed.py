"""Seed built-in holiday events for a region (idempotent) — called from the API and seed."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.forecast.calendar import events_for_years
from app.models import HolidayEvent, HolidaySource, Region


def seed_region_holidays(
    db: Session, org_id: uuid.UUID, region: Region, years: list[int] | None = None
) -> int:
    years = years or [
        date.today().year - 2,
        date.today().year - 1,
        date.today().year,
        date.today().year + 1,
    ]
    wanted = {(ev.name, ev.start) for ev in events_for_years(region.code, years)}
    # Built-in rows from an older calendar (e.g. a duplicate Ashura, staging bug #23) are
    # removed for the seeded years; custom events are never touched.
    removed = 0
    for e in db.scalars(
        select(HolidayEvent).where(
            HolidayEvent.region_id == region.id, HolidayEvent.source == HolidaySource.builtin
        )
    ):
        if e.start_date.year in years and (e.name, e.start_date) not in wanted:
            db.delete(e)
            removed += 1
    db.flush()
    existing = {
        (e.name, e.start_date)
        for e in db.scalars(select(HolidayEvent).where(HolidayEvent.region_id == region.id))
    }
    n = 0
    for ev in events_for_years(region.code, years):
        if (ev.name, ev.start) in existing:
            continue
        db.add(
            HolidayEvent(
                org_id=org_id,
                region_id=region.id,
                name=ev.name,
                start_date=ev.start,
                end_date=ev.end,
                recurring=True,
                source=HolidaySource.builtin,
                kind=ev.kind,
            )
        )
        existing.add((ev.name, ev.start))
        n += 1
    db.flush()
    return n
