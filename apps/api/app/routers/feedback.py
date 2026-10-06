"""POST /feedback — in-app feedback (beta program). Stored, then forwarded to the team."""

from __future__ import annotations

import html
import logging

import httpx
from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.config import settings
from app.deps import DB, Ctx
from app.models import Feedback, Organization

log = logging.getLogger(__name__)
router = APIRouter(tags=["feedback"])


class FeedbackIn(BaseModel):
    message: str = Field(..., min_length=3, max_length=5000)
    rating: int | None = Field(None, ge=1, le=5)
    page: str | None = Field(None, max_length=300)


class FeedbackOut(BaseModel):
    id: str


def _notify(org: Organization | None, fb: Feedback) -> None:
    """Best effort: email REPORT_EMAILS and post to the alert hook. Never fails the request."""
    who = f"{org.name if org else 'unknown'}{' (beta)' if org and org.is_beta else ''}"
    text = f"Feedback from {who} — {fb.rating or '-'}/5 on {fb.page or '?'}:\n{fb.message}"
    try:
        with httpx.Client(timeout=5) as c:
            to = [e.strip() for e in settings.report_emails.split(",") if e.strip()]
            if to and settings.resend_api_key:
                c.post(
                    "https://api.resend.com/emails",
                    json={
                        "from": settings.email_from,
                        "to": to,
                        "subject": f"Stockcast feedback: {who}",
                        "html": f"<pre style='white-space:pre-wrap'>{html.escape(text)}</pre>",
                    },
                    headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                )
            if settings.alert_webhook_url:
                c.post(settings.alert_webhook_url, json={"text": text})
    except httpx.HTTPError:
        log.warning("feedback notify failed for %s", fb.id)


@router.post("/feedback", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
def send_feedback(db: DB, ctx: Ctx, body: FeedbackIn) -> FeedbackOut:
    fb = Feedback(
        org_id=ctx.org_id,
        actor=ctx.actor,
        rating=body.rating,
        message=body.message.strip(),
        page=body.page,
    )
    db.add(fb)
    db.commit()
    _notify(db.get(Organization, ctx.org_id), fb)
    return FeedbackOut(id=str(fb.id))
