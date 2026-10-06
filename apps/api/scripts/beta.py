"""Beta program ops (run on the api service: `railway run uv run python -m scripts.beta ...`).

candidates [--all]          waitlist rows that fit the beta (make products + 2+ channels)
grant <slug|shop|email>     mark a workspace as beta (50% off 6 months via Shopify billing)
invited <email> [...]       record that an invite was sent to waitlist emails
feedback [--days N]         recent in-app feedback
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Feedback, Organization, User, WaitlistSignup
from app.services.waitlist import beta_fit


def candidates(db: Session, include_all: bool = False) -> list[WaitlistSignup]:
    rows = db.scalars(select(WaitlistSignup).order_by(WaitlistSignup.created_at)).all()
    return [r for r in rows if include_all or beta_fit(r.channels, r.makes_products)]


def find_org(db: Session, key: str) -> Organization | None:
    org = db.scalar(
        select(Organization).where(or_(Organization.slug == key, Organization.shopify_shop == key))
    )
    if org is None and "@" in key:
        user = db.scalar(select(User).where(User.email == key.lower()))
        org = db.get(Organization, user.org_id) if user else None
    return org


def grant(db: Session, key: str) -> Organization | None:
    org = find_org(db, key)
    if org is not None:
        org.is_beta = True
        db.commit()
    return org


def mark_invited(db: Session, emails: list[str], now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    rows = db.scalars(
        select(WaitlistSignup).where(WaitlistSignup.email.in_([e.lower() for e in emails]))
    ).all()
    for r in rows:
        r.beta_invited_at = now
    db.commit()
    return len(rows)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates")
    c.add_argument("--all", action="store_true")
    g = sub.add_parser("grant")
    g.add_argument("key")
    i = sub.add_parser("invited")
    i.add_argument("emails", nargs="+")
    f = sub.add_parser("feedback")
    f.add_argument("--days", type=int, default=14)
    args = ap.parse_args(argv)
    with SessionLocal() as db:
        if args.cmd == "candidates":
            for r in candidates(db, args.all):
                status = f"invited {r.beta_invited_at:%Y-%m-%d}" if r.beta_invited_at else "new"
                print(
                    f"{r.email}\t{r.company or ''}\t{','.join(r.channels)}\t"
                    f"makes={r.makes_products}\t{status}\t{(r.notes or '')[:60]}"
                )
        elif args.cmd == "grant":
            org = grant(db, args.key)
            print(f"beta granted to {org.name} ({org.slug})" if org else "no such workspace")
        elif args.cmd == "invited":
            print(f"marked {mark_invited(db, args.emails)} invite(s)")
        elif args.cmd == "feedback":
            since = datetime.now(UTC) - timedelta(days=args.days)
            for fb in db.scalars(
                select(Feedback).where(Feedback.created_at >= since).order_by(Feedback.created_at)
            ):
                print(
                    f"{fb.created_at:%Y-%m-%d} {fb.rating or '-'}/5 {fb.page or ''}: {fb.message}"
                )


if __name__ == "__main__":
    main()
