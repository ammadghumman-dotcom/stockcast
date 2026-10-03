"""Shared HTTP plumbing for REST connectors: token-bucket rate limits + retry on 429/5xx.

Each connector declares `RATE_LIMITS = {"name": (rate_per_second, burst)}` and calls
`self.http.request(name, method, url, ...)`. Buckets are per connector *instance* (one per
sync run), which matches how Amazon/eBay throttle: per app + seller.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.ingest.base import ConnectorError

_sleep = time.sleep  # patched in tests


class TokenBucket:
    """Classic token bucket: `burst` tokens max, refilled at `rate` per second."""

    def __init__(self, rate: float, burst: int) -> None:
        self.rate, self.burst = float(rate), int(burst)
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self.waited = 0.0  # total seconds slept (visible to tests / logs)

    def take(self) -> None:
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens < 1:
            wait = (1 - self.tokens) / self.rate
            self.waited += wait
            _sleep(wait)
            self.tokens = 1
        self.tokens -= 1


class RateLimitedHttp:
    def __init__(
        self,
        limits: dict[str, tuple[float, int]],
        *,
        client: httpx.Client | None = None,
        name: str = "upstream",
        max_attempts: int = 5,
    ) -> None:
        self.buckets = {k: TokenBucket(r, b) for k, (r, b) in limits.items()}
        self.client = client or httpx.Client(timeout=60)
        self.name = name
        self.max_attempts = max_attempts

    def request(self, bucket: str, method: str, url: str, **kw: Any) -> httpx.Response:
        b = self.buckets.get(bucket)
        for attempt in range(self.max_attempts):
            if b:
                b.take()
            try:
                res = self.client.request(method, url, **kw)
            except httpx.HTTPError as exc:
                raise ConnectorError(f"{self.name} request failed: {exc}") from exc
            if res.status_code == 429 or res.status_code in (502, 503, 504):
                _sleep(float(res.headers.get("Retry-After", 2 * (attempt + 1))))
                continue
            if res.status_code == 401:
                raise ConnectorError(f"{self.name} token rejected (401); reconnect the channel")
            if res.status_code >= 400:
                raise ConnectorError(f"{self.name} {res.status_code}: {res.text[:200]}")
            return res
        raise ConnectorError(f"{self.name} throttled repeatedly; giving up for this run")

    def json(self, bucket: str, method: str, url: str, **kw: Any) -> Any:
        res = self.request(bucket, method, url, **kw)
        return res.json() if res.content else {}
