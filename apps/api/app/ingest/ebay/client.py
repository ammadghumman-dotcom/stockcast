"""eBay Sell APIs client: user refresh token -> access token, marketplace header, paging."""

from __future__ import annotations

import base64
import time
from collections.abc import Iterator
from typing import Any

import httpx

from app.config import settings
from app.ingest.base import ConnectorError
from app.ingest.http import RateLimitedHttp

API_BASE = "https://api.ebay.com"
SANDBOX_BASE = "https://api.sandbox.ebay.com"
TOKEN_PATH = "/identity/v1/oauth2/token"
SCOPES = [
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
]
# eBay publishes daily quotas (e.g. 5k-100k calls/day) rather than per-second limits; these
# buckets keep bursts polite and let 429s back off.
RATE_LIMITS: dict[str, tuple[float, int]] = {"fulfillment": (5.0, 10), "inventory": (5.0, 10)}
PAGE = 200


class EbayClient:
    def __init__(
        self,
        refresh_token: str,
        marketplace_id: str,
        *,
        client: httpx.Client | None = None,
        sandbox: bool = False,
    ) -> None:
        self.refresh_token = refresh_token
        self.marketplace_id = marketplace_id
        self.base = SANDBOX_BASE if sandbox else API_BASE
        self.http = RateLimitedHttp(RATE_LIMITS, client=client, name="eBay")
        self._token: str | None = None
        self._token_expires = 0.0

    def access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        if not settings.ebay_client_id or not settings.ebay_client_secret:
            raise ConnectorError("EBAY_CLIENT_ID/SECRET not configured")
        basic = base64.b64encode(
            f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode()
        ).decode()
        try:
            res = self.http.client.post(
                f"{self.base}{TOKEN_PATH}",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "scope": " ".join(SCOPES),
                },
                headers={"Authorization": f"Basic {basic}"},
            )
        except httpx.HTTPError as exc:
            raise ConnectorError(f"eBay token request failed: {exc}") from exc
        if res.status_code != 200:
            raise ConnectorError(f"eBay token rejected ({res.status_code}); reconnect eBay")
        body = res.json()
        self._token = body["access_token"]
        self._token_expires = time.time() + int(body.get("expires_in", 7200))
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token()}",
            "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
            "Accept": "application/json",
        }

    def paginate(self, bucket: str, path: str, key: str, params: dict[str, Any]) -> Iterator[dict]:
        offset = 0
        while True:
            body = self.http.json(
                bucket,
                "GET",
                f"{self.base}{path}",
                params={**params, "limit": PAGE, "offset": offset},
                headers=self._headers(),
            )
            items = body.get(key) or []
            yield from items
            offset += len(items)
            if not items or offset >= int(body.get("total") or 0):
                return
