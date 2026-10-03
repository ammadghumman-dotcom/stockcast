"""Thin Shopify Admin GraphQL client: auth header, cursor pagination, throttle-aware retry."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx

from app.config import settings
from app.ingest.base import ConnectorError


class ShopifyGraphQL:
    def __init__(self, shop: str, access_token: str, *, client: httpx.Client | None = None):
        self.shop = shop
        self.url = f"https://{shop}/admin/api/{settings.shopify_api_version}/graphql.json"
        self._client = client or httpx.Client(timeout=30)
        self._headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(5):
            try:
                res = self._client.post(
                    self.url,
                    json={"query": query, "variables": variables or {}},
                    headers=self._headers,
                )
            except httpx.HTTPError as exc:
                raise ConnectorError(f"Shopify request failed: {exc}") from exc
            if res.status_code == 429:
                time.sleep(float(res.headers.get("Retry-After", 2)))
                continue
            if res.status_code >= 500:
                raise ConnectorError(f"Shopify {res.status_code}: {res.text[:200]}")
            if res.status_code == 401:
                raise ConnectorError("Shopify token rejected (401); reconnect the store")
            body = res.json()
            errors = body.get("errors") or []
            if any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors):
                time.sleep(2 * (attempt + 1))
                continue
            if errors:
                raise ConnectorError(f"Shopify GraphQL error: {errors[0].get('message')}")
            return body["data"]
        raise ConnectorError("Shopify throttled repeatedly; giving up for this run")

    def paginate(
        self, query: str, root: str, variables: dict[str, Any] | None = None, page: int = 250
    ) -> Iterator[dict[str, Any]]:
        """Yield `node` dicts from a connection field `root`, following `pageInfo.endCursor`."""
        cursor: str | None = None
        while True:
            data = self.query(query, {**(variables or {}), "first": page, "after": cursor})
            conn = data[root]
            for edge in conn["edges"]:
                yield edge["node"]
            if not conn["pageInfo"]["hasNextPage"]:
                return
            cursor = conn["pageInfo"]["endCursor"]


PRODUCTS_QUERY = """
query Products($first: Int!, $after: String) {
  products(first: $first, after: $after, query: "status:active") {
    edges { node {
      id title productType status
      variants(first: 100) { edges { node {
        id sku title price inventoryItem { id unitCost { amount } }
      } } }
    } }
    pageInfo { hasNextPage endCursor }
  }
}
"""

ORDERS_QUERY = """
query Orders($first: Int!, $after: String, $q: String) {
  orders(first: $first, after: $after, query: $q, sortKey: CREATED_AT) {
    edges { node {
      id createdAt cancelledAt test
      lineItems(first: 100) { edges { node {
        quantity
        variant { id sku }
        discountedTotalSet { shopMoney { amount } }
      } } }
    } }
    pageInfo { hasNextPage endCursor }
  }
}
"""

INVENTORY_QUERY = """
query Inventory($first: Int!, $after: String) {
  inventoryItems(first: $first, after: $after) {
    edges { node {
      id sku
      variant { id }
      inventoryLevels(first: 20) { edges { node {
        location { id name }
        quantities(names: ["available", "incoming"]) { name quantity }
      } } }
    } }
    pageInfo { hasNextPage endCursor }
  }
}
"""

WEBHOOK_CREATE = """
mutation WebhookCreate($topic: WebhookSubscriptionTopic!, $url: URL!) {
  webhookSubscriptionCreate(topic: $topic, webhookSubscription: {callbackUrl: $url, format: JSON}) {
    webhookSubscription { id }
    userErrors { field message }
  }
}
"""


def gid_to_id(gid: str | None) -> str | None:
    """gid://shopify/ProductVariant/123 -> '123'."""
    return gid.rsplit("/", 1)[-1] if gid else None
