"""CSV import/export. Files land on a channel of type `csv` (auto-created as 'CSV Import')."""

import json
import uuid
from datetime import date

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from app.deps import DB, OrgId
from app.ingest import upsert
from app.ingest.csv_connector import KINDS, CsvConnector, CsvParseError
from app.ingest.export import export_csv
from app.ingest.records import IngestResult
from app.models import Channel, ChannelType
from app.schemas.ingest import ImportResponse
from app.services import crud

router = APIRouter(tags=["imports"])
MAX_UPLOAD = 25 * 1024 * 1024


def _csv_channel(db, org_id: uuid.UUID, channel_id: uuid.UUID | None) -> Channel:
    if channel_id:
        ch = crud.get_scoped(db, Channel, org_id, channel_id)
        if ch.type != ChannelType.csv:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "not a csv channel")
        return ch
    ch = db.scalar(select(Channel).where(Channel.org_id == org_id, Channel.type == ChannelType.csv))
    if ch is None:
        ch = Channel(org_id=org_id, name="CSV Import", type=ChannelType.csv)
        db.add(ch)
        db.flush()
    return ch


@router.post("/imports", response_model=ImportResponse)
async def import_csv(
    db: DB,
    org_id: OrgId,
    products: UploadFile | None = File(None),
    sales: UploadFile | None = File(None),
    inventory: UploadFile | None = File(None),
    bom: UploadFile | None = File(None),
    mapping: str | None = Form(None, description='JSON: {"sales": {"units": "Qty"}}'),
    channel_id: uuid.UUID | None = Form(None),
    strict: bool = Form(False, description="Reject the whole upload if any row is invalid"),
):
    files: dict[str, bytes] = {}
    for kind, up in (
        ("products", products),
        ("sales", sales),
        ("inventory", inventory),
        ("bom", bom),
    ):
        if up is not None:
            data = await up.read()
            if len(data) > MAX_UPLOAD:
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"{kind}.csv too large")
            files[kind] = data
    if not files:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "no files uploaded")
    try:
        mapping_obj = json.loads(mapping) if mapping else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "mapping is not JSON") from exc

    channel = _csv_channel(db, org_id, channel_id)
    conn = CsvConnector(channel, files, mapping_obj)
    results: list[IngestResult] = []
    savepoint = db.begin_nested()  # strict mode undoes only this import, never caller state
    try:
        # Order matters: products first so sales/inventory/bom can resolve SKUs.
        if "products" in files:
            results.append(upsert.upsert_products(db, org_id, conn.fetch_products(), None))
        if "bom" in files:
            results.append(upsert.upsert_bom(db, org_id, conn.fetch_bom()))
        if "inventory" in files:
            results.append(upsert.upsert_inventory(db, org_id, conn.fetch_inventory(), None))
        if "sales" in files:
            results.append(upsert.upsert_sales(db, org_id, channel, conn.fetch_sales(date.min)))
    except CsvParseError as exc:
        savepoint.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    # fold parse-time row errors into the matching result
    for r in results:
        r.errors = conn.errors.get(r.kind, []) + r.errors
        r.received += len(conn.errors.get(r.kind, []))
    if strict and any(r.errors for r in results):
        savepoint.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"detail": "row errors", "results": [r.model_dump() for r in results]},
        )
    savepoint.commit()
    db.commit()
    return ImportResponse(channel_id=channel.id, results=results)


@router.get("/exports/{kind}.csv", response_class=PlainTextResponse)
def export(db: DB, org_id: OrgId, kind: str, channel_id: uuid.UUID | None = None):
    if kind not in KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown kind {kind}")
    return PlainTextResponse(
        export_csv(db, org_id, kind, channel_id),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'},
    )
