"""Transactional email via Resend.

Kinds: welcome, trial_ending, sync_failed, weekly_stockout_digest. Every send goes through
`send(...)`, which is idempotent on (org, kind, dedupe_key) via `email_log` — a retried Celery
task or a double webhook never emails twice. Without RESEND_API_KEY mails are logged with
status "skipped" so dev/test still exercise the templates.

`_http_client()` is the injection seam for tests (httpx.MockTransport).
"""

from __future__ import annotations

import html
import logging
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Channel,
    EmailLog,
    Organization,
    PlanningRun,
    Product,
    Recommendation,
    SyncRun,
    User,
)

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=20)


def _recipients(db: Session, org: Organization, min_role: str = "admin") -> list[str]:
    """Owners + admins (viewers never get operational mail); billing_email as fallback."""
    from app.deps import ROLE_RANK

    users = db.scalars(select(User).where(User.org_id == org.id)).all()
    emails = sorted({u.email for u in users if ROLE_RANK.get(u.role, 0) >= ROLE_RANK[min_role]})
    if not emails and org.billing_email:
        emails = [org.billing_email]
    return emails


def _layout(title: str, body_html: str, cta: tuple[str, str] | None = None) -> str:
    button = (
        f'<p style="margin:24px 0"><a href="{html.escape(cta[1])}" '
        'style="background:#111827;color:#fff;padding:10px 18px;border-radius:6px;'
        f'text-decoration:none;font-weight:600">{html.escape(cta[0])}</a></p>'
        if cta
        else ""
    )
    return (
        '<div style="font-family:Inter,Segoe UI,Arial,sans-serif;max-width:560px;margin:0 auto;'
        'color:#111827;line-height:1.5">'
        f'<h2 style="font-size:20px;margin:0 0 12px">{html.escape(title)}</h2>'
        f"{body_html}{button}"
        '<p style="color:#6b7280;font-size:12px;margin-top:32px">Stockcast · demand forecasting '
        "and raw-material planning for ecommerce brands</p></div>"
    )


def send(
    db: Session,
    org: Organization,
    *,
    kind: str,
    dedupe_key: str,
    to: list[str],
    subject: str,
    html_body: str,
    client: httpx.Client | None = None,
) -> EmailLog | None:
    """Send once per (org, kind, dedupe_key). Returns the log row, or None if already sent."""
    if not to:
        return None
    existing = db.scalar(
        select(EmailLog).where(
            EmailLog.org_id == org.id, EmailLog.kind == kind, EmailLog.dedupe_key == dedupe_key
        )
    )
    if existing is not None:
        return None
    row = EmailLog(
        org_id=org.id,
        kind=kind,
        dedupe_key=dedupe_key,
        to=", ".join(to)[:320],
        subject=subject[:300],
        status="skipped",
        sent_at=datetime.now(UTC),
    )
    if settings.resend_api_key:
        c = client or _http_client()
        res = c.post(
            RESEND_URL,
            json={"from": settings.email_from, "to": to, "subject": subject, "html": html_body},
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        )
        if res.status_code >= 300:
            row.status = "failed"
            log.warning("resend %s: %s %s", kind, res.status_code, res.text[:200])
        else:
            row.status, row.provider_id = "sent", (res.json() or {}).get("id")
    db.add(row)
    db.commit()
    return row


# --------------------------------------------------------------------------- templates
def send_welcome(db: Session, org: Organization, email: str | None = None) -> EmailLog | None:
    to = [email] if email else _recipients(db, org, "owner")
    days = settings.trial_days
    body = (
        f"<p>Welcome to Stockcast, {html.escape(org.name)}.</p>"
        f"<p>Your {days}-day trial is on — connect a store or upload a CSV, and tonight's run will "
        "produce your first demand forecast and reorder recommendations.</p>"
        "<ol><li>Connect Shopify or import products, sales and stock</li>"
        "<li>Add suppliers and lead times</li>"
        "<li>Review the recommendations and send your first PO</li></ol>"
    )
    return send(
        db,
        org,
        kind="welcome",
        dedupe_key=str(org.id),
        to=to,
        subject="Welcome to Stockcast",
        html_body=_layout(
            "Welcome to Stockcast", body, ("Open Stockcast", f"{settings.web_base_url}/onboarding")
        ),
    )


def send_trial_ending(db: Session, org: Organization, days_left: int) -> EmailLog | None:
    ends = org.trial_ends_at.date().isoformat() if org.trial_ends_at else "soon"
    body = (
        f"<p>Your Stockcast trial ends in <b>{days_left} day{'s' if days_left != 1 else ''}</b> "
        f"({ends}).</p><p>Pick a plan to keep nightly forecasts, recommendations and purchase "
        "orders running. Starter $39/mo · Growth $99/mo · Scale $249/mo.</p>"
    )
    return send(
        db,
        org,
        kind="trial_ending",
        dedupe_key=f"{org.id}:{days_left}",
        to=_recipients(db, org, "admin"),
        subject=f"Your Stockcast trial ends in {days_left} day{'s' if days_left != 1 else ''}",
        html_body=_layout(
            "Trial ending soon",
            body,
            ("Choose a plan", f"{settings.web_base_url}/settings?tab=billing"),
        ),
    )


def send_sync_failed(db: Session, run: SyncRun) -> EmailLog | None:
    org = db.get(Organization, run.org_id)
    channel = db.get(Channel, run.channel_id)
    if org is None or channel is None:
        return None
    body = (
        f"<p>The sync for <b>{html.escape(channel.name)}</b> ({channel.type.value}) failed after "
        f"{run.attempts} attempt{'s' if run.attempts != 1 else ''}.</p>"
        f'<pre style="background:#f3f4f6;padding:12px;border-radius:6px;white-space:pre-wrap">'
        f"{html.escape((run.error or 'unknown error')[:600])}</pre>"
        "<p>Forecasts keep using the last good data. Reconnect the channel or retry the sync "
        "from Settings.</p>"
    )
    return send(
        db,
        org,
        kind="sync_failed",
        dedupe_key=str(run.id),
        to=_recipients(db, org, "admin"),
        subject=f"Sync failed: {channel.name}",
        html_body=_layout(
            "Sync failed", body, ("Open channels", f"{settings.web_base_url}/settings")
        ),
    )


def send_weekly_digest(
    db: Session, org: Organization, run: PlanningRun, week: date | None = None
) -> EmailLog | None:
    week = week or date.today()
    week_key = f"{week.isocalendar().year}-W{week.isocalendar().week:02d}"
    recs = db.execute(
        select(Recommendation, Product)
        .join(Product, Product.id == Recommendation.product_id)
        .where(
            Recommendation.org_id == org.id,
            Recommendation.run_id == run.id,
            Recommendation.health.in_(["stockout", "at_risk"]),
        )
        .order_by(Recommendation.stockout_date.asc().nulls_last())
        .limit(25)
    ).all()
    counts = run.health_counts or {}
    n_out, n_risk = int(counts.get("stockout", 0)), int(counts.get("at_risk", 0))
    rows = "".join(
        f"<tr><td style='padding:4px 8px'>{html.escape(p.sku)}</td>"
        f"<td style='padding:4px 8px'>{html.escape(p.name)[:40]}</td>"
        f"<td style='padding:4px 8px'>{r.health}</td>"
        f"<td style='padding:4px 8px'>{r.stockout_date.isoformat() if r.stockout_date else '-'}"
        "</td>"
        f"<td style='padding:4px 8px'>{r.action} {float(r.qty):g}</td></tr>"
        for r, p in recs
    )
    body = (
        f"<p><b>{n_out}</b> SKU{'s' if n_out != 1 else ''} out of stock, <b>{n_risk}</b> at risk "
        f"within lead time, as of {run.as_of or week}.</p>"
        + (
            "<table style='border-collapse:collapse;font-size:13px'><tr>"
            + "".join(
                f"<th align=left style='padding:4px 8px'>{h}</th>"
                for h in ("SKU", "Product", "Health", "Stockout", "Action")
            )
            + f"</tr>{rows}</table>"
            if rows
            else "<p>Nothing at risk this week — nice.</p>"
        )
    )
    return send(
        db,
        org,
        kind="weekly_stockout_digest",
        dedupe_key=f"{org.id}:{week_key}",
        to=_recipients(db, org, "viewer"),
        subject=f"Stockout digest: {n_out} out, {n_risk} at risk",
        html_body=_layout(
            "Weekly stockout digest",
            body,
            ("See recommendations", f"{settings.web_base_url}/recommendations"),
        ),
    )


# --------------------------------------------------------------------------- batch helpers
def trial_ending_orgs(
    db: Session, now: datetime | None = None, days_before: int = 3
) -> list[tuple[Organization, int]]:
    """Trial orgs whose trial ends in exactly `days_before` days (or 1 day) from `now`."""
    now = now or datetime.now(UTC)
    out: list[tuple[Organization, int]] = []
    orgs = db.scalars(
        select(Organization).where(
            Organization.plan == "trial",
            Organization.trial_ends_at.is_not(None),
            Organization.trial_ends_at > now,
            Organization.trial_ends_at <= now + timedelta(days=days_before),
        )
    ).all()
    for org in orgs:
        assert org.trial_ends_at is not None
        left = max((org.trial_ends_at - now).days, 0) + (
            1 if (org.trial_ends_at - now).seconds else 0
        )
        if left in (days_before, 1):
            out.append((org, left))
    return out


def latest_run_for_digest(db: Session, org_id: uuid.UUID) -> PlanningRun | None:
    return db.scalar(
        select(PlanningRun)
        .where(PlanningRun.org_id == org_id, PlanningRun.status == "success")
        .order_by(PlanningRun.finished_at.desc())
        .limit(1)
    )
