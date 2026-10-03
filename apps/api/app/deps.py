"""Request-scoped dependencies.

Org scoping: until Clerk auth lands (Step 7) the caller identifies its org with the
`X-Org-Id` header. Every data route depends on `OrgId` so no query can run unscoped.
"""

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Organization

DB = Annotated[Session, Depends(get_db)]


def get_org_id(
    db: DB,
    x_org_id: Annotated[str | None, Header(alias="X-Org-Id")] = None,
) -> uuid.UUID:
    if not x_org_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-Org-Id header required")
    try:
        org_id = uuid.UUID(x_org_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-Org-Id must be a UUID") from exc
    if db.scalar(select(Organization.id).where(Organization.id == org_id)) is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown organization")
    return org_id


OrgId = Annotated[uuid.UUID, Depends(get_org_id)]
