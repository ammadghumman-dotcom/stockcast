"""Amazon Selling Partner API client: LWA token exchange, regional endpoints, per-endpoint
token buckets (rates from the SP-API usage plans), Reports API create/poll/download."""

from __future__ import annotations

import gzip
import io
import time
from typing import Any

import httpx

from app.config import settings
from app.ingest.base import ConnectorError
from app.ingest.http import RateLimitedHttp, _sleep

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"

ENDPOINTS = {
    "na": "https://sellingpartnerapi-na.amazon.com",
    "eu": "https://sellingpartnerapi-eu.amazon.com",
    "fe": "https://sellingpartnerapi-fe.amazon.com",
}
# marketplace id -> region (subset; unknown ids default to "na")
MARKETPLACE_REGION = {
    "ATVPDKIKX0DER": "na",  # US
    "A2EUQ1WTGCTBG2": "na",  # CA
    "A1AM78C64UM0Y8": "na",  # MX
    "A2Q3Y263D00KWC": "na",  # BR
    "A1F83G8C2ARO7P": "eu",  # UK
    "A1PA6795UKMFR9": "eu",  # DE
    "A13V1IB3VIYZZH": "eu",  # FR
    "APJ6JRA9NG5V4": "eu",  # IT
    "A1RKKUPIHCS9HS": "eu",  # ES
    "A1805IZSGTT6HS": "eu",  # NL
    "A2NODRKZP88ZB9": "eu",  # SE
    "A1C3SOZRARQ6R3": "eu",  # PL
    "A21TJRUUN4KGV": "eu",  # IN
    "A2VIGQ35RCS4UG": "eu",  # AE
    "A17E79C6D8DWNP": "eu",  # SA
    "A1VC38T7YXB528": "fe",  # JP
    "A39IBJ37TRP1C6": "fe",  # AU
    "A19VAU5U5O7RUS": "fe",  # SG
}

# (requests per second, burst) — SP-API "usage plans"
RATE_LIMITS: dict[str, tuple[float, int]] = {
    "orders": (0.0167, 20),
    "order_items": (0.5, 30),
    "create_report": (0.0167, 15),
    "get_report": (2.0, 15),
    "report_document": (0.0167, 15),
    "fba_inventory": (2.0, 2),
    "catalog": (2.0, 2),
    "download": (5.0, 5),
}

REPORT_POLL_SECONDS = 15
REPORT_MAX_WAIT_SECONDS = 1800


class AmazonClient:
    def __init__(
        self,
        refresh_token: str,
        marketplace_id: str,
        *,
        client: httpx.Client | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        self.refresh_token = refresh_token
        self.marketplace_id = marketplace_id
        self.region = MARKETPLACE_REGION.get(marketplace_id, "na")
        self.base = ENDPOINTS[self.region]
        self.client_id = client_id or settings.amazon_lwa_client_id
        self.client_secret = client_secret or settings.amazon_lwa_client_secret
        self.http = RateLimitedHttp(RATE_LIMITS, client=client, name="Amazon SP-API")
        self._token: str | None = None
        self._token_expires = 0.0

    # ---- auth ----
    def access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        if not self.client_id or not self.client_secret:
            raise ConnectorError("AMAZON_LWA_CLIENT_ID/SECRET not configured")
        try:
            res = self.http.client.post(
                LWA_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
        except httpx.HTTPError as exc:
            raise ConnectorError(f"LWA token request failed: {exc}") from exc
        if res.status_code != 200:
            raise ConnectorError(f"LWA token rejected ({res.status_code}); reconnect Amazon")
        body = res.json()
        self._token = body["access_token"]
        self._token_expires = time.time() + int(body.get("expires_in", 3600))
        return self._token

    def _headers(self) -> dict[str, str]:
        return {"x-amz-access-token": self.access_token(), "Accept": "application/json"}

    def get(self, bucket: str, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.http.json(
            bucket, "GET", f"{self.base}{path}", params=params, headers=self._headers()
        )

    def post(self, bucket: str, path: str, body: dict[str, Any]) -> Any:
        return self.http.json(
            bucket, "POST", f"{self.base}{path}", json=body, headers=self._headers()
        )

    # ---- orders ----
    def iter_orders(self, created_after: str) -> Any:
        params: dict[str, Any] = {
            "MarketplaceIds": self.marketplace_id,
            "CreatedAfter": created_after,
            "MaxResultsPerPage": 100,
        }
        while True:
            payload = self.get("orders", "/orders/v0/orders", params)["payload"]
            yield from payload.get("Orders", [])
            token = payload.get("NextToken")
            if not token:
                return
            params = {"NextToken": token}

    def order_items(self, order_id: str) -> list[dict]:
        items: list[dict] = []
        params: dict[str, Any] | None = None
        while True:
            payload = self.get("order_items", f"/orders/v0/orders/{order_id}/orderItems", params)[
                "payload"
            ]
            items.extend(payload.get("OrderItems", []))
            token = payload.get("NextToken")
            if not token:
                return items
            params = {"NextToken": token}

    # ---- reports ----
    def run_report(self, report_type: str, **options: Any) -> str:
        """Create a report, poll until DONE, download and return the decoded text."""
        body = {
            "reportType": report_type,
            "marketplaceIds": [self.marketplace_id],
            **{k: v for k, v in options.items() if v is not None},
        }
        report_id = self.post("create_report", "/reports/2021-06-30/reports", body)["reportId"]
        deadline = time.time() + REPORT_MAX_WAIT_SECONDS
        while True:
            rep = self.get("get_report", f"/reports/2021-06-30/reports/{report_id}")
            status = rep.get("processingStatus")
            if status == "DONE":
                break
            if status in ("CANCELLED", "FATAL"):
                raise ConnectorError(f"Amazon report {report_type} {status}")
            if time.time() > deadline:
                raise ConnectorError(f"Amazon report {report_type} timed out")
            _sleep(REPORT_POLL_SECONDS)
        doc = self.get(
            "report_document", f"/reports/2021-06-30/documents/{rep['reportDocumentId']}"
        )
        res = self.http.request("download", "GET", doc["url"])
        raw = res.content
        if doc.get("compressionAlgorithm") == "GZIP":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        return raw.decode("utf-8", errors="replace")

    # ---- FBA inventory ----
    def iter_fba_summaries(self) -> Any:
        params: dict[str, Any] = {
            "details": "true",
            "granularityType": "Marketplace",
            "granularityId": self.marketplace_id,
            "marketplaceIds": self.marketplace_id,
        }
        while True:
            body = self.get("fba_inventory", "/fba/inventory/v1/summaries", params)
            yield from (body.get("payload") or {}).get("inventorySummaries", [])
            token = (body.get("pagination") or {}).get("nextToken")
            if not token:
                return
            params = {**params, "nextToken": token}

    # ---- catalog ----
    def catalog_items(self, asins: list[str]) -> dict[str, dict]:
        """ASIN -> summary (itemName, productType...) in batches of 20."""
        out: dict[str, dict] = {}
        for i in range(0, len(asins), 20):
            batch = asins[i : i + 20]
            body = self.get(
                "catalog",
                "/catalog/2022-04-01/items",
                {
                    "identifiers": ",".join(batch),
                    "identifiersType": "ASIN",
                    "marketplaceIds": self.marketplace_id,
                    "includedData": "summaries",
                },
            )
            for item in body.get("items", []):
                summary = next(
                    (
                        s
                        for s in item.get("summaries", [])
                        if s.get("marketplaceId") == self.marketplace_id
                    ),
                    (item.get("summaries") or [{}])[0],
                )
                out[item["asin"]] = summary
        return out
