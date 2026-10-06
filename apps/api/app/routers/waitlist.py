"""POST /waitlist — public form on the landing page (rate-limited per IP, honeypot-guarded)."""

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, EmailStr, Field

from app.deps import DB
from app.ratelimit import limiter
from app.services import waitlist


class WaitlistIn(BaseModel):
    email: EmailStr
    name: str | None = Field(None, max_length=200)
    company: str | None = Field(None, max_length=200)
    website: str | None = Field(None, max_length=300)
    channels: list[str] = Field(default_factory=list, max_length=10)
    makes_products: bool = False
    notes: str | None = Field(None, max_length=2000)
    source: str = Field("landing", max_length=60)
    # Honeypot: invisible on the page, so only bots fill it in
    fax: str | None = Field(None, max_length=200)


class WaitlistOut(BaseModel):
    ok: bool
    beta_fit: bool


router = APIRouter(tags=["marketing"])


@router.post("/waitlist", response_model=WaitlistOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
def join_waitlist(request: Request, body: WaitlistIn, db: DB) -> WaitlistOut:
    fit = waitlist.beta_fit(body.channels, body.makes_products)
    if body.fax:  # bot: answer like a success, store nothing
        return WaitlistOut(ok=True, beta_fit=fit)
    waitlist.join(
        db,
        email=str(body.email),
        name=body.name,
        company=body.company,
        website=body.website,
        channels=body.channels,
        makes_products=body.makes_products,
        notes=body.notes,
        source=body.source,
    )
    db.commit()
    return WaitlistOut(ok=True, beta_fit=fit)
