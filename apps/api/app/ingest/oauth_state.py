"""Signed, short-lived OAuth `state` carrying {org_id, channel_id} through a redirect."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from app.config import settings
from app.ingest.base import ConnectorError

STATE_TTL = 900


def _sign(raw: str) -> str:
    return hmac.new(settings.credentials_key.encode(), raw.encode(), hashlib.sha256).hexdigest()


def make_state(**payload: Any) -> str:
    data = json.dumps({**payload, "n": secrets.token_hex(8), "t": int(time.time())})
    raw = base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")
    return f"{raw}.{_sign(raw)}"


def read_state(state: str) -> dict[str, Any]:
    try:
        raw, sig = state.rsplit(".", 1)
    except ValueError as exc:
        raise ConnectorError("malformed state") from exc
    if not hmac.compare_digest(sig, _sign(raw)):
        raise ConnectorError("state signature mismatch")
    data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    if time.time() - data["t"] > STATE_TTL:
        raise ConnectorError("state expired; start the connection again")
    return data
