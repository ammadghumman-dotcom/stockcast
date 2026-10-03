"""WooCommerce REST API v3 client (consumer key/secret over HTTPS basic auth)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from app.ingest.http import RateLimitedHttp

RATE_LIMITS: dict[str, tuple[float, int]] = {"rest": (5.0, 10)}


class WooClient:
    def __init__(self, url: str, key: str, secret: str, *, client: httpx.Client | None = None):
        self.base = url.rstrip("/") + "/wp-json/wc/v3"
        self.auth = (key, secret)
        self.http = RateLimitedHttp(RATE_LIMITS, client=client, name="WooCommerce")

    def paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict]:
        page = 1
        while True:
            res = self.http.request(
                "rest",
                "GET",
                f"{self.base}{path}",
                params={**(params or {}), "per_page": 100, "page": page},
                auth=self.auth,
            )
            items = res.json()
            yield from items
            total_pages = int(res.headers.get("X-WP-TotalPages", 1))
            if page >= total_pages or not items:
                return
            page += 1
