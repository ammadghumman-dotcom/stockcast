"""Audit trail for purchase orders, planning settings and billing changes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.deps import AuthContext
from app.models import AuditLog


def snapshot(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    """JSON-safe copy of selected ORM attributes (dates/decimals/uuids become strings)."""
    out: dict[str, Any] = {}
    for f in fields:
        v = getattr(obj, f, None)
        if isinstance(v, (datetime, uuid.UUID)):
            v = str(v)
        elif isinstance(v, Decimal):
            v = float(v)
        elif hasattr(v, "isoformat"):
            v = v.isoformat()
        elif hasattr(v, "value"):  # enums
            v = v.value
        out[f] = v
    return out


def record(
    db: Session,
    ctx: AuthContext | None,
    *,
    org_id: uuid.UUID | None = None,
    action: str,
    entity: str,
    entity_id: Any = None,
    before: dict | None = None,
    after: dict | None = None,
    actor: str | None = None,
) -> AuditLog:
    """Add an audit row to the current transaction (caller commits)."""
    row = AuditLog(
        org_id=org_id or (ctx.org_id if ctx else None),
        user_id=ctx.user_id if ctx else None,
        actor=actor or (ctx.actor if ctx else "system"),
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=before,
        after=after,
        at=datetime.now(UTC),
    )
    db.add(row)
    return row
