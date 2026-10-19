"""Beta program: waitlist review, invites, beta pricing, feedback (staff page + scripts/beta.py)."""

from __future__ import annotations

import html
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Feedback, Organization, User, WaitlistSignup
from app.services.waitlist import beta_fit

log = logging.getLogger(__name__)
RESEND_URL = "https://api.resend.com/emails"


def staff_list() -> set[str]:
    return {e.strip().lower() for e in settings.staff_emails.split(",") if e.strip()}


def is_staff(email: str | None) -> bool:
    return email is not None and email.lower() in staff_list()


def waitlist(db: Session, include_all: bool = False) -> list[WaitlistSignup]:
    rows = db.scalars(select(WaitlistSignup).order_by(WaitlistSignup.created_at)).all()
    return [r for r in rows if include_all or beta_fit(r.channels, r.makes_products)]


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=20)


def invite_html(row: WaitlistSignup) -> tuple[str, str]:
    who = html.escape(row.name or "there")
    company = f" for {html.escape(row.company)}" if row.company else ""
    link = f"{settings.web_base_url.rstrip('/')}/sign-up?beta=1"
    subject = "You're in: your Stockcast beta invite"
    body = (
        '<div style="font-family:Inter,Segoe UI,Arial,sans-serif;max-width:560px;margin:0 auto;'
        'color:#111827;line-height:1.5">'
        f"<p>Hi {who},</p>"
        f"<p>Thanks for joining the Stockcast waitlist{company}. We'd like you in the beta.</p>"
        "<p>Stockcast forecasts demand for every SKU across your sales channels and turns it into "
        "production runs and purchase orders, down to raw materials.</p>"
        "<p>Beta workspaces get <b>50% off for the first 6 months</b>. Sign up with this email "
        "address and the discount is applied to your workspace automatically.</p>"
        f'<p style="margin:24px 0"><a href="{html.escape(link)}" style="background:#111827;'
        'color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:600">'
        "Create your workspace</a></p>"
        "<p>Just reply to this email with questions or feedback; it comes straight to us.</p>"
        "</div>"
    )
    return subject, body


def send_invites(
    db: Session,
    emails: list[str],
    *,
    resend: bool = False,
    client: httpx.Client | None = None,
) -> dict[str, list[str]]:
    """Email a beta invite to waitlist rows; already-invited rows are skipped unless `resend`."""
    wanted = {e.strip().lower() for e in emails if e.strip()}
    rows = db.scalars(select(WaitlistSignup).where(WaitlistSignup.email.in_(wanted))).all()
    out: dict[str, list[str]] = {"sent": [], "skipped": [], "failed": [], "unknown": []}
    out["unknown"] = sorted(wanted - {r.email for r in rows})
    c = client or _http_client()
    for r in rows:
        if r.beta_invited_at and not resend:
            out["skipped"].append(r.email)
            continue
        subject, body = invite_html(r)
        if settings.resend_api_key:
            res = c.post(
                RESEND_URL,
                json={
                    "from": settings.email_from,
                    "to": [r.email],
                    "subject": subject,
                    "html": body,
                    **({"reply_to": sorted(staff_list())[0]} if staff_list() else {}),
                },
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            )
            if res.status_code >= 300:
                log.warning("beta invite %s: %s %s", r.email, res.status_code, res.text[:200])
                out["failed"].append(r.email)
                continue
        r.beta_invited_at = datetime.now(UTC)
        out["sent"].append(r.email)
    db.commit()
    return out


def find_org(db: Session, key: str) -> Organization | None:
    key = key.strip()
    org = db.scalar(
        select(Organization).where(or_(Organization.slug == key, Organization.shopify_shop == key))
    )
    if org is None and "@" in key:
        user = db.scalar(select(User).where(User.email == key.lower()))
        org = db.get(Organization, user.org_id) if user else None
    return org


def set_beta(db: Session, key: str, on: bool = True) -> Organization | None:
    org = find_org(db, key)
    if org is not None:
        org.is_beta = on
        db.commit()
    return org


def flag_invited_workspace(db: Session, org: Organization, email: str | None) -> bool:
    """A new workspace whose creator was invited from the waitlist gets beta pricing."""
    if not email or org.is_beta:
        return False
    row = db.scalar(select(WaitlistSignup).where(WaitlistSignup.email == email.lower()))
    if row is None or row.beta_invited_at is None:
        return False
    org.is_beta = True
    db.commit()
    return True


def beta_workspaces(db: Session) -> list[Organization]:
    return list(
        db.scalars(
            select(Organization).where(Organization.is_beta.is_(True)).order_by(Organization.name)
        )
    )


def recent_feedback(db: Session, days: int = 14) -> list[tuple[Feedback, str | None]]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(Feedback, Organization.name)
        .join(Organization, Organization.id == Feedback.org_id, isouter=True)
        .where(Feedback.created_at >= since)
        .order_by(Feedback.created_at.desc())
    ).all()
    return [(fb, name) for fb, name in rows]
