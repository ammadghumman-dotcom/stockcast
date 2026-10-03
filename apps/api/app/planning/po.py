"""Purchase orders: draft from recommendations, export CSV/PDF, send via Resend, receive."""

from __future__ import annotations

import csv
import io
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    InventoryLevel,
    Location,
    Organization,
    POStatus,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    Recommendation,
    Supplier,
    SupplierProduct,
)


class POError(ValueError):
    pass


def draft_from_recommendations(
    db: Session, org_id: uuid.UUID, recommendation_ids: list[uuid.UUID] | None, *, run_id: uuid.UUID
) -> list[PurchaseOrder]:
    """Group reorder recommendations by supplier into draft POs (one PO per supplier)."""
    q = select(Recommendation).where(
        Recommendation.org_id == org_id,
        Recommendation.run_id == run_id,
        Recommendation.action == "reorder",
        Recommendation.po_id.is_(None),
    )
    if recommendation_ids:
        q = q.where(Recommendation.id.in_(recommendation_ids))
    recs = db.scalars(q).all()
    if not recs:
        return []
    no_supplier = [r for r in recs if r.supplier_id is None]
    if no_supplier:
        skus = db.scalars(
            select(Product.sku).where(Product.id.in_([r.product_id for r in no_supplier]))
        ).all()
        raise POError(f"no supplier on file for: {', '.join(sorted(skus))}")

    prices = {
        (sp.supplier_id, sp.product_id): sp.price
        for sp in db.scalars(select(SupplierProduct).where(SupplierProduct.org_id == org_id))
    }
    costs = dict(
        db.execute(select(Product.id, Product.unit_cost).where(Product.org_id == org_id)).all()
    )
    default_loc = db.scalar(
        select(Location.id)
        .where(Location.org_id == org_id)
        .order_by(Location.is_default.desc())
        .limit(1)
    )
    by_supplier: dict[uuid.UUID, list[Recommendation]] = defaultdict(list)
    for r in recs:
        if r.supplier_id is not None:
            by_supplier[r.supplier_id].append(r)

    pos = []
    for sid, group in by_supplier.items():
        supplier = db.get(Supplier, sid)
        po = PurchaseOrder(
            org_id=org_id,
            supplier_id=sid,
            location_id=default_loc,
            number=_next_number(db, org_id),
            status=POStatus.draft,
            expected_date=max(r.expected_date for r in group if r.expected_date)
            if any(r.expected_date for r in group)
            else None,
            currency=supplier.currency if supplier else "USD",
            notes="Drafted from recommendations "
            + ", ".join(sorted({r.reason.split(" —")[0] for r in group}))[:1000],
        )
        db.add(po)
        db.flush()
        for i, r in enumerate(sorted(group, key=lambda x: x.order_by_date or date.max), start=1):
            price = prices.get((sid, r.product_id)) or costs.get(r.product_id) or Decimal(0)
            db.add(
                PurchaseOrderLine(
                    purchase_order_id=po.id,
                    product_id=r.product_id,
                    qty=r.qty,
                    unit_price=price,
                    line_no=i,
                )
            )
            r.po_id = po.id
        pos.append(po)
    db.flush()
    return pos


def _next_number(db: Session, org_id: uuid.UUID) -> str:
    n = (
        db.scalar(
            select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.org_id == org_id)
        )
        or 0
    )
    return f"PO-{date.today():%Y%m}-{n + 1:04d}"


def po_total(po: PurchaseOrder) -> Decimal:
    return sum((ln.qty * ln.unit_price for ln in po.lines), Decimal(0))


# --------------------------------------------------------------------------- exports
def po_rows(db: Session, po: PurchaseOrder) -> list[dict]:
    skus = dict(
        db.execute(
            select(
                Product.id,
                Product.sku,
            ).where(Product.id.in_([ln.product_id for ln in po.lines]))
        ).all()
    )
    names = dict(
        db.execute(
            select(Product.id, Product.name).where(
                Product.id.in_([ln.product_id for ln in po.lines])
            )
        ).all()
    )
    units = dict(
        db.execute(
            select(Product.id, Product.unit).where(
                Product.id.in_([ln.product_id for ln in po.lines])
            )
        ).all()
    )
    return [
        {
            "line": ln.line_no,
            "sku": skus.get(ln.product_id, ""),
            "name": names.get(ln.product_id, ""),
            "qty": f"{ln.qty.normalize():f}",
            "unit": units.get(ln.product_id, "unit"),
            "unit_price": f"{ln.unit_price:.4f}",
            "line_total": f"{ln.qty * ln.unit_price:.2f}",
        }
        for ln in sorted(po.lines, key=lambda x: x.line_no)
    ]


def po_csv(db: Session, po: PurchaseOrder) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(
        buf,
        fieldnames=["line", "sku", "name", "qty", "unit", "unit_price", "line_total"],
        lineterminator="\n",
    )
    w.writeheader()
    w.writerows(po_rows(db, po))
    return buf.getvalue()


def po_pdf(db: Session, po: PurchaseOrder) -> bytes:
    from fpdf import FPDF

    org = db.get(Organization, po.org_id)
    supplier = db.get(Supplier, po.supplier_id)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"Purchase Order {po.number}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"From: {org.name if org else ''}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(
        0,
        6,
        f"To: {supplier.name if supplier else ''}  {supplier.email or '' if supplier else ''}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.cell(
        0,
        6,
        f"Status: {po.status.value}   Expected: {po.expected_date or '-'}   "
        f"Currency: {po.currency}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(4)
    widths = [10, 35, 70, 25, 25, 25]
    headers = ["#", "SKU", "Item", "Qty", "Price", "Total"]
    pdf.set_font("Helvetica", "B", 10)
    for w_, h in zip(widths, headers, strict=True):
        pdf.cell(w_, 7, h, border=1)
    pdf.ln()
    pdf.set_font("Helvetica", "", 10)
    for r in po_rows(db, po):
        vals = [
            str(r["line"]),
            r["sku"],
            r["name"][:38],
            f"{r['qty']} {r['unit']}",
            r["unit_price"],
            r["line_total"],
        ]
        for w_, v in zip(widths, vals, strict=True):
            pdf.cell(w_, 7, v, border=1)
        pdf.ln()
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(sum(widths[:-1]), 7, "Total", border=1, align="R")
    pdf.cell(widths[-1], 7, f"{po_total(po):.2f}", border=1)
    pdf.ln()
    if po.notes:
        pdf.ln(4)
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 5, po.notes)
    return bytes(pdf.output())


# --------------------------------------------------------------------------- send / receive
def _http_client() -> httpx.Client:
    """Factory so tests can swap in a MockTransport without touching the global httpx class."""
    return httpx.Client(timeout=20)


def send_po(db: Session, po: PurchaseOrder, *, client: httpx.Client | None = None) -> dict:
    """Email the PO (PDF + CSV attached) to the supplier via Resend; marks it `sent`."""
    if po.status != POStatus.draft:
        raise POError(f"PO {po.number} is {po.status.value}, only drafts can be sent")
    supplier = db.get(Supplier, po.supplier_id)
    if not supplier or not supplier.email:
        raise POError("supplier has no email address")
    if not settings.resend_api_key:
        raise POError("RESEND_API_KEY not configured")
    import base64

    org = db.get(Organization, po.org_id)
    rows = po_rows(db, po)
    body_lines = [f"{r['qty']} {r['unit']} x {r['sku']} {r['name']}" for r in rows]
    payload = {
        "from": settings.email_from,
        "to": [supplier.email],
        "subject": f"Purchase order {po.number} from {org.name if org else 'Stockcast'}",
        "text": f"Hello {supplier.name},\n\nPlease find purchase order {po.number} attached.\n\n"
        + "\n".join(body_lines)
        + f"\n\nTotal: {po_total(po):.2f} {po.currency}\n"
        + f"Expected delivery: {po.expected_date or 'TBC'}\n\nThank you.",
        "attachments": [
            {"filename": f"{po.number}.pdf", "content": base64.b64encode(po_pdf(db, po)).decode()},
            {
                "filename": f"{po.number}.csv",
                "content": base64.b64encode(po_csv(db, po).encode()).decode(),
            },
        ],
    }
    c = client or _http_client()
    res = c.post(
        "https://api.resend.com/emails",
        json=payload,
        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
    )
    if res.status_code >= 300:
        raise POError(f"Resend error {res.status_code}: {res.text[:200]}")
    po.status, po.sent_at = POStatus.sent, datetime.now(UTC)
    db.flush()
    return res.json()


def receive_po(
    db: Session, po: PurchaseOrder, received: dict[uuid.UUID, Decimal] | None = None
) -> PurchaseOrder:
    """Book received quantities into inventory at the PO's location (default: all lines in full)."""
    if po.status == POStatus.draft:
        raise POError("cannot receive a draft PO; send it first")
    loc_id = po.location_id or db.scalar(
        select(Location.id)
        .where(Location.org_id == po.org_id)
        .order_by(Location.is_default.desc())
        .limit(1)
    )
    if loc_id is None:
        loc = Location(org_id=po.org_id, name="Main Warehouse", is_default=True)
        db.add(loc)
        db.flush()
        loc_id = loc.id
    all_done = True
    for ln in po.lines:
        qty = (
            received.get(ln.id, ln.qty - ln.received_qty) if received else ln.qty - ln.received_qty
        )
        qty = min(max(Decimal(qty), Decimal(0)), Decimal(ln.qty - ln.received_qty))
        if qty <= 0:
            all_done = all_done and ln.received_qty >= ln.qty
            continue
        inv = db.scalar(
            select(InventoryLevel).where(
                InventoryLevel.product_id == ln.product_id, InventoryLevel.location_id == loc_id
            )
        )
        if inv is None:
            inv = InventoryLevel(org_id=po.org_id, product_id=ln.product_id, location_id=loc_id)
            db.add(inv)
        inv.on_hand = (inv.on_hand or 0) + qty
        inv.inbound = max(Decimal(inv.inbound or 0) - qty, Decimal(0))
        inv.as_of = datetime.now(UTC)
        ln.received_qty += qty
        all_done = all_done and ln.received_qty >= ln.qty
    if all_done:
        po.status, po.received_at = POStatus.received, datetime.now(UTC)
    db.flush()
    return po
