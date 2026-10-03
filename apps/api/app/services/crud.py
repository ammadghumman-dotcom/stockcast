"""Generic org-scoped CRUD. Every read/write filters by org_id so tenants never cross."""

import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base


def list_scoped[M: Base](
    db: Session, model: type[M], org_id: uuid.UUID, *, limit: int = 100, offset: int = 0
) -> Sequence[M]:
    stmt = (
        select(model)
        .where(model.org_id == org_id)  # type: ignore[attr-defined]
        .order_by(model.created_at.desc())  # type: ignore[attr-defined]
        .limit(limit)
        .offset(offset)
    )
    return db.scalars(stmt).all()


def get_scoped[M: Base](db: Session, model: type[M], org_id: uuid.UUID, obj_id: uuid.UUID) -> M:
    obj = db.scalar(
        select(model).where(
            model.id == obj_id,  # type: ignore[attr-defined]
            model.org_id == org_id,  # type: ignore[attr-defined]
        )  # type: ignore[arg-type]
    )
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} not found")
    return obj


def create_scoped[M: Base](db: Session, model: type[M], org_id: uuid.UUID, data: BaseModel) -> M:
    obj = model(org_id=org_id, **data.model_dump())
    db.add(obj)
    _commit(db)
    db.refresh(obj)
    return obj


def update_scoped[M: Base](
    db: Session, model: type[M], org_id: uuid.UUID, obj_id: uuid.UUID, data: BaseModel
) -> M:
    obj = get_scoped(db, model, org_id, obj_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    _commit(db)
    db.refresh(obj)
    return obj


def assert_owned[M: Base](
    db: Session, model: type[M], org_id: uuid.UUID, obj_id: uuid.UUID
) -> None:
    """Raise 422 if a referenced row belongs to another org (or does not exist)."""
    if (
        db.scalar(
            select(model.id).where(  # type: ignore[attr-defined]
                model.id == obj_id,  # type: ignore[attr-defined]
                model.org_id == org_id,  # type: ignore[attr-defined]
            )
        )
        is None
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{model.__name__} {obj_id} not found"
        )


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        detail: Any = getattr(exc.orig, "diag", None)
        msg = getattr(detail, "message_detail", None) or "Constraint violation"
        raise HTTPException(status.HTTP_409_CONFLICT, msg) from exc
