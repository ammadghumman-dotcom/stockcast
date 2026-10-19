"""Beta program ops from a shell. Day to day, use the staff Beta page (/staff/beta) instead.

Run on the api service: `railway run uv run python -m scripts.beta ...`.

candidates [--all]          waitlist rows that fit the beta (make products + 2+ channels)
grant <slug|shop|email>     mark a workspace as beta (50% off 6 months via Shopify billing)
invited <email> [...]       record that an invite was sent to waitlist emails
feedback [--days N]         recent in-app feedback
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Feedback, Organization, WaitlistSignup
from app.services import beta as beta_svc

# Same logic as the staff Beta page (app/services/beta.py); kept for shell use.
find_org = beta_svc.find_org


def candidates(db: Session, include_all: bool = False) -> list[WaitlistSignup]:
    return beta_svc.waitlist(db, include_all)


def grant(db: Session, key: str) -> Organization | None:
    return beta_svc.set_beta(db, key, True)


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
