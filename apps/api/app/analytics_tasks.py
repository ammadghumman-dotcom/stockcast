"""Celery: PostHog capture + weekly activation cohort report (Mondays 08:00 UTC)."""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Organization, OrgMilestone
from app.worker import celery

log = logging.getLogger(__name__)

FUNNEL = ("first_channel_connected", "first_forecast_viewed", "first_po_created")
LABELS = {
    "first_channel_connected": "Connected",
    "first_forecast_viewed": "Viewed forecast",
    "first_po_created": "Created PO",
}


def _http() -> httpx.Client:
    return httpx.Client(timeout=10)


@celery.task(
    name="analytics.capture", autoretry_for=(httpx.HTTPError,), retry_backoff=True, max_retries=3
)
def capture_event(payload: dict) -> None:
    with _http() as c:
        res = c.post(f"{settings.posthog_host.rstrip('/')}/i/v0/e/", json=payload)
        res.raise_for_status()


@dataclass
class Cohort:
    week: date  # Monday of the signup week
    orgs: int
    reached: dict[str, int]

    def pct(self, key: str) -> float:
        return 0.0 if not self.orgs else 100.0 * self.reached.get(key, 0) / self.orgs


def cohorts(db: Session, *, weeks: int = 8, today: date | None = None) -> list[Cohort]:
    """Signup-week cohorts (newest first) and how many orgs reached each funnel milestone."""
    today = today or datetime.now(UTC).date()
    this_monday = today - timedelta(days=today.weekday())
    start = this_monday - timedelta(weeks=weeks - 1)
    week = func.date_trunc("week", Organization.created_at)
    base = (
        select(week.label("week"), func.count(Organization.id))
        .where(Organization.created_at >= start)
        .group_by(week)
    )
    sizes = {w.date(): n for w, n in db.execute(base)}
    reached_q = (
        select(week, OrgMilestone.key, func.count(func.distinct(OrgMilestone.org_id)))
        .join(OrgMilestone, OrgMilestone.org_id == Organization.id)
        .where(Organization.created_at >= start, OrgMilestone.key.in_(FUNNEL))
        .group_by(week, OrgMilestone.key)
    )
    reached: dict[date, dict[str, int]] = {}
    for w, key, n in db.execute(reached_q):
        reached.setdefault(w.date(), {})[key] = n
    out = []
    for i in range(weeks):
        wk = this_monday - timedelta(weeks=i)
        out.append(Cohort(week=wk, orgs=sizes.get(wk, 0), reached=reached.get(wk, {})))
    return out


def render(rows: list[Cohort]) -> tuple[str, str]:
    """(plain text for chat hooks, html table for email)."""
    head = ["Signup week", "Workspaces", *(LABELS[k] for k in FUNNEL)]
    lines = [" | ".join(head)]
    trs = []
    for c in rows:
        cells = [c.week.isoformat(), str(c.orgs)] + [
            f"{c.reached.get(k, 0)} ({c.pct(k):.0f}%)" for k in FUNNEL
        ]
        lines.append(" | ".join(cells))
        trs.append("<tr>" + "".join(f"<td>{html.escape(x)}</td>" for x in cells) + "</tr>")
    th = "".join(f"<th align='left'>{html.escape(h)}</th>" for h in head)
    table = (
        "<table cellpadding='6' style='border-collapse:collapse;font-size:14px'>"
        f"<tr>{th}</tr>{''.join(trs)}</table>"
    )
    return "\n".join(lines), table


@celery.task(name="analytics.weekly_cohort_report")
def weekly_cohort_report() -> str:
    with SessionLocal() as db:
        text, table = render(cohorts(db))
    subject = "Stockcast weekly activation cohorts"
    with _http() as c:
        to = [e.strip() for e in settings.report_emails.split(",") if e.strip()]
        if to and settings.resend_api_key:
            c.post(
                "https://api.resend.com/emails",
                json={
                    "from": settings.email_from,
                    "to": to,
                    "subject": subject,
                    "html": f"<h2>{subject}</h2>{table}",
                },
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            )
        if settings.alert_webhook_url:
            c.post(settings.alert_webhook_url, json={"text": f"*{subject}*\n```\n{text}\n```"})
    log.info("cohort report\n%s", text)
    return text
