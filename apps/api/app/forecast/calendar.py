"""Built-in demand events per region: retail moments with lead-in windows + national holidays.

`builtin_events(region_code, year)` -> list of Event. Dates come from the `holidays` package
where the event is calendar-dependent (Eid, Diwali, Thanksgiving) and from fixed rules
otherwise. Every event has a lead-in window because demand moves before the day itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import holidays
from dateutil.easter import easter

# region code -> ISO country used for national holidays. EU has no single calendar: retail
# events only, plus Christmas.
REGION_COUNTRY = {
    "US": "US",
    "CA": "CA",
    "UK": "GB",
    "GB": "GB",
    "DE": "DE",
    "FR": "FR",
    "AU": "AU",
    "AE": "AE",
    "SA": "SA",
    "PK": "PK",
    "IN": "IN",
    "EU": None,
}


@dataclass(frozen=True)
class Event:
    name: str
    start: date
    end: date
    kind: str = "retail"  # retail | religious | national


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _find(country: str, year: int, *needles: str) -> list[date]:
    try:
        cal = holidays.country_holidays(country, years=[year], language="en_US")
    except Exception:
        return []
    out = []
    for d, name in cal.items():
        low = name.lower()
        if any(n in low for n in needles):
            out.append(d)
    return sorted(out)


def builtin_events(region_code: str, year: int) -> list[Event]:
    code = region_code.upper()
    country = REGION_COUNTRY.get(code, code)
    ev: list[Event] = []

    # ---- global retail moments
    ev.append(Event("Christmas", date(year, 11, 20), date(year, 12, 24)))
    ev.append(Event("Valentine's Day", date(year, 2, 1), date(year, 2, 14)))
    thanksgiving = _nth_weekday(year, 11, 3, 4)  # 4th Thursday
    black_friday = thanksgiving + timedelta(days=1)
    ev.append(Event("Black Friday", black_friday - timedelta(days=7), black_friday))
    ev.append(
        Event("Cyber Monday", black_friday + timedelta(days=1), black_friday + timedelta(days=3))
    )
    ev.append(Event("Prime Day", date(year, 7, 8), date(year, 7, 16)))  # mid-July; Amazon varies
    ev.append(Event("Singles Day", date(year, 11, 1), date(year, 11, 11)))

    # ---- Mother's Day: 2nd Sunday of May almost everywhere; UK = Mothering Sunday (Lent)
    if code in ("UK", "GB"):
        ms = easter(year) - timedelta(days=21)
    else:
        ms = _nth_weekday(year, 5, 6, 2)
    ev.append(Event("Mother's Day", ms - timedelta(days=14), ms))

    # ---- religious (calendar from `holidays`): Ramadan is the 30 days before Eid al-Fitr
    eid_country = country if country in ("AE", "SA", "PK", "IN", "GB", "US") else "AE"
    eid = _find(eid_country, year, "eid al-fitr", "eid-ul-fitr", "eid ul-fitr", "eid al fitr")
    if eid:
        ev.append(Event("Ramadan/Eid", eid[0] - timedelta(days=30), eid[0], "religious"))
    if code in ("IN", "UK", "GB", "US", "AE", "SG", "MY"):
        diwali = _find("IN", year, "diwali", "deepavali")
        if diwali:
            ev.append(Event("Diwali", diwali[0] - timedelta(days=14), diwali[0], "religious"))

    # ---- national holidays (single days, lead-in 3 days) excluding ones covered above
    if country:
        cal: dict = {}
        try:
            cal = dict(holidays.country_holidays(country, years=[year], language="en_US"))
        except Exception:
            cal = {}
        covered = ("christmas", "eid", "diwali", "thanksgiving", "new year")
        for d, name in sorted(cal.items()):
            if any(c in name.lower() for c in covered):
                continue
            ev.append(Event(name.split(" (")[0][:100], d - timedelta(days=3), d, "national"))
    return ev


def events_for_years(region_code: str, years: list[int]) -> list[Event]:
    out: list[Event] = []
    for y in years:
        out.extend(builtin_events(region_code, y))
    return out
