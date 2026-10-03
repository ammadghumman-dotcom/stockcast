import uuid
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select

from app.deps import DB, OrgId
from app.models import PlanningRun, Product, PurchaseOrder, Supplier
from app.planning import po as po_svc
from app.planning.engine import latest_planning_run
from app.schemas.planning import DraftPORequest, POLineRead, PurchaseOrderRead, ReceiveRequest
from app.services import crud

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])


def _read(db, po: PurchaseOrder) -> PurchaseOrderRead:
    skus = dict(
        db.execute(
            select(Product.id, Product.sku).where(
                Product.id.in_([ln.product_id for ln in po.lines])
            )
        ).all()
    )
    supplier = db.get(Supplier, po.supplier_id)
    r = PurchaseOrderRead.model_validate(
        {
            **po.__dict__,
            "total": po_svc.po_total(po),
            "supplier_name": supplier.name if supplier else None,
            "lines": [
                POLineRead.model_validate({**ln.__dict__, "sku": skus.get(ln.product_id)})
                for ln in sorted(po.lines, key=lambda x: x.line_no)
            ],
        }
    )
    return r


@router.post(
    "/from-recommendations",
    response_model=list[PurchaseOrderRead],
    status_code=status.HTTP_201_CREATED,
)
def from_recommendations(db: DB, org_id: OrgId, body: DraftPORequest):
    run = (
        crud.get_scoped(db, PlanningRun, org_id, body.run_id)
        if body.run_id
        else latest_planning_run(db, org_id)
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no planning run yet")
    try:
        pos = po_svc.draft_from_recommendations(db, org_id, body.recommendation_ids, run_id=run.id)
    except po_svc.POError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.commit()
    for po in pos:
        db.refresh(po)
    return [_read(db, po) for po in pos]


@router.get("", response_model=list[PurchaseOrderRead])
def list_pos(
    db: DB,
    org_id: OrgId,
    status_: str | None = Query(None, alias="status"),
    limit: int = Query(100, le=500),
):
    pos = crud.list_scoped(db, PurchaseOrder, org_id, limit=limit)
    if status_:
        pos = [p for p in pos if p.status.value == status_]
    return [_read(db, p) for p in pos]


@router.get("/{po_id}", response_model=PurchaseOrderRead)
def get_po(db: DB, org_id: OrgId, po_id: uuid.UUID):
    return _read(db, crud.get_scoped(db, PurchaseOrder, org_id, po_id))


@router.get("/{po_id}/export.csv", response_class=PlainTextResponse)
def po_csv(db: DB, org_id: OrgId, po_id: uuid.UUID):
    po = crud.get_scoped(db, PurchaseOrder, org_id, po_id)
    return PlainTextResponse(
        po_svc.po_csv(db, po),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{po.number}.csv"'},
    )


@router.get("/{po_id}/export.pdf")
def po_pdf(db: DB, org_id: OrgId, po_id: uuid.UUID):
    po = crud.get_scoped(db, PurchaseOrder, org_id, po_id)
    return Response(
        po_svc.po_pdf(db, po),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{po.number}.pdf"'},
    )


@router.post("/{po_id}/send", response_model=PurchaseOrderRead)
def send_po(db: DB, org_id: OrgId, po_id: uuid.UUID):
    po = crud.get_scoped(db, PurchaseOrder, org_id, po_id)
    try:
        po_svc.send_po(db, po)
    except po_svc.POError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.commit()
    db.refresh(po)
    return _read(db, po)


@router.post("/{po_id}/mark-sent", response_model=PurchaseOrderRead)
def mark_sent(db: DB, org_id: OrgId, po_id: uuid.UUID):
    """Record that the PO was sent outside the app (no email)."""
    from datetime import UTC, datetime

    from app.models import POStatus

    po = crud.get_scoped(db, PurchaseOrder, org_id, po_id)
    if po.status != POStatus.draft:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "only drafts can be marked sent")
    po.status, po.sent_at = POStatus.sent, datetime.now(UTC)
    db.commit()
    db.refresh(po)
    return _read(db, po)


@router.post("/{po_id}/receive", response_model=PurchaseOrderRead)
def receive_po(db: DB, org_id: OrgId, po_id: uuid.UUID, body: ReceiveRequest | None = None):
    po = crud.get_scoped(db, PurchaseOrder, org_id, po_id)
    try:
        po_svc.receive_po(
            db, po, {k: Decimal(v) for k, v in body.lines.items()} if body and body.lines else None
        )
    except po_svc.POError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.commit()
    db.refresh(po)
    return _read(db, po)
