"""Per-org rate limiting: heavy endpoints get 429 after RATE_LIMIT_HEAVY within a minute."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.ratelimit import limiter


def test_heavy_endpoint_is_limited_per_org(client: TestClient, headers: dict, other_headers: dict):
    limiter.reset()
    codes = [client.get("/exports/products.csv", headers=headers).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429
    # another org has its own bucket
    assert client.get("/exports/products.csv", headers=other_headers).status_code == 200
    # the default bucket for ordinary endpoints is separate and much larger
    assert client.get("/products", headers=headers).status_code == 200
    limiter.reset()
