"""Amazon SP-API notifications.

SP-API delivers notifications to SQS/EventBridge, not to an HTTPS URL directly. The supported
production wiring is EventBridge -> API destination -> this endpoint, with a shared secret the
API destination sends as `X-Amz-Webhook-Signature: sha256=<hmac(body)>` (configure the
connection's header with the HMAC computed by a small Lambda transform, or use the simpler
`X-Amz-Webhook-Token: <secret>` bearer comparison). Both are constant-time verified here.

Handled: ANY_OFFER_CHANGED / ORDER_CHANGE / FBA_INVENTORY_AVAILABILITY_CHANGES -> enqueue an
incremental sync for the seller's channel. Deduped on the notification id.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app import crypto
from app.config import settings
from app.deps import DB
from app.ingest.tasks import enqueue_sync
from app.models import Channel, ChannelType, ProcessedWebhook

router = APIRouter(tags=["amazon"])

SYNC_TOPICS = {"ORDER_CHANGE", "FBA_INVENTORY_AVAILABILITY_CHANGES", "ANY_OFFER_CHANGED"}


def verify_signature(body: bytes, signature: str | None, token: str | None) -> bool:
    secret = settings.amazon_webhook_secret
    if not secret:
        return False
    if token is not None:
        return hmac.compare_digest(token, secret)
    if signature and signature.startswith("sha256="):
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature[7:], digest)
    return False


@router.post("/webhooks/amazon", status_code=200)
async def amazon_notification(request: Request, db: DB):
    raw = await request.body()
    if not verify_signature(
        raw,
        request.headers.get("X-Amz-Webhook-Signature"),
        request.headers.get("X-Amz-Webhook-Token"),
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad signature")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "body is not JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "body must be an object")
    meta = payload.get("NotificationMetadata") or payload.get("notificationMetadata") or {}
    ntype = payload.get("NotificationType") or payload.get("notificationType") or ""
    nid = meta.get("NotificationId") or meta.get("notificationId") or str(uuid.uuid4())
    seller = (
        meta.get("SellerId")
        or (payload.get("Payload") or {}).get("SellerId")
        or (payload.get("payload") or {}).get("sellerId")
    )
    marketplace = (payload.get("Payload") or {}).get("MarketplaceId") or (
        payload.get("payload") or {}
    ).get("marketplaceId")

    channels = db.scalars(
        select(Channel).where(
            Channel.type == ChannelType.amazon, Channel.credentials_encrypted.is_not(None)
        )
    ).all()
    target = None
    for ch in channels:
        creds = json.loads(crypto.decrypt(ch.credentials_encrypted or ""))
        if seller and creds.get("seller_id") == seller:
            if not marketplace or creds.get("marketplace_id") == marketplace:
                target = ch
                break
    if target is None:
        return {"received": True, "result": "no matching channel"}

    inserted = db.execute(
        pg_insert(ProcessedWebhook)
        .values(
            id=uuid.uuid4(),
            channel_id=target.id,
            webhook_id=str(nid)[:100],
            topic=f"amazon:{ntype}"[:100],
            received_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(constraint="uq_processed_webhooks")
        .returning(ProcessedWebhook.id)
    ).first()
    db.commit()
    if inserted is None:
        return {"received": True, "result": "duplicate"}
    if ntype in SYNC_TOPICS:
        enqueue_sync(db, target, trigger="webhook")
        return {"received": True, "result": "sync enqueued"}
    return {"received": True, "result": "ignored"}
