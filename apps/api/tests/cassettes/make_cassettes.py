"""Generate vcrpy cassettes for the Shopify connector tests.

We don't have a live dev store in CI, so these cassettes are synthesized from Shopify's
documented Admin GraphQL response shapes. To re-record against a real store, delete the
yaml files, set SHOPIFY_* env vars + a real token, and run pytest with --record-mode=once.

Run:  uv run python -m tests.cassettes.make_cassettes
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

HERE = Path(__file__).parent
SHOP = "demo-candle.myshopify.com"
URL = f"https://{SHOP}/admin/api/2025-07/graphql.json"


def _interaction(data: dict, status: int = 200) -> dict:
    return {
        "request": {"method": "POST", "uri": URL, "body": "<graphql>", "headers": {}},
        "response": {
            "status": {"code": status, "message": "OK"},
            "headers": {"Content-Type": ["application/json"]},
            "body": {"string": json.dumps({"data": data})},
        },
    }


def _page(root: str, nodes: list, has_next: bool, cursor: str | None) -> dict:
    return {
        root: {
            "edges": [{"node": n} for n in nodes],
            "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
        }
    }


def _variant(vid: int, sku: str, title: str, price: str, cost: str | None) -> dict:
    return {
        "id": f"gid://shopify/ProductVariant/{vid}",
        "sku": sku,
        "title": title,
        "price": price,
        "inventoryItem": {
            "id": f"gid://shopify/InventoryItem/{vid + 1000}",
            "unitCost": {"amount": cost} if cost else None,
        },
    }


PRODUCTS_P1 = [
    {
        "id": "gid://shopify/Product/1",
        "title": "Vanilla Candle",
        "productType": "Candles",
        "status": "ACTIVE",
        "variants": {
            "edges": [
                {"node": _variant(101, "CND-VAN-200", "200g", "14.00", "4.20")},
                {"node": _variant(102, "CND-VAN-400", "400g", "24.00", "7.50")},
            ]
        },
    },
    {
        "id": "gid://shopify/Product/2",
        "title": "Oud Oil 10ml",
        "productType": "Perfume Oils",
        "status": "ACTIVE",
        "variants": {"edges": [{"node": _variant(201, "", "Default Title", "18.00", None)}]},
    },
]
PRODUCTS_P2 = [
    {
        "id": "gid://shopify/Product/3",
        "title": "Discovery Set",
        "productType": "Gift Sets",
        "status": "ACTIVE",
        "variants": {
            "edges": [{"node": _variant(301, "GFT-DISC", "Default Title", "22.00", "6.80")}]
        },
    }
]


def _order(oid: int, created: str, lines: list[tuple[int, str, int, str]], **extra) -> dict:
    return {
        "id": f"gid://shopify/Order/{oid}",
        "createdAt": created,
        "cancelledAt": extra.get("cancelledAt"),
        "test": extra.get("test", False),
        "lineItems": {
            "edges": [
                {
                    "node": {
                        "quantity": qty,
                        "variant": {"id": f"gid://shopify/ProductVariant/{vid}", "sku": sku},
                        "discountedTotalSet": {"shopMoney": {"amount": amt}},
                    }
                }
                for vid, sku, qty, amt in lines
            ]
        },
    }


ORDERS_P1 = [
    _order(5001, "2026-09-01T10:00:00Z", [(101, "CND-VAN-200", 2, "28.00")]),
    _order(5002, "2026-09-01T15:30:00Z", [(101, "CND-VAN-200", 1, "12.60"), (201, "", 3, "54.00")]),
    _order(5003, "2026-09-02T09:00:00Z", [(102, "CND-VAN-400", 1, "24.00")]),
    _order(
        5004,
        "2026-09-02T11:00:00Z",
        [(101, "CND-VAN-200", 5, "70.00")],
        cancelledAt="2026-09-02T12:00:00Z",
    ),
]
ORDERS_P2 = [
    _order(5005, "2026-09-03T08:00:00Z", [(301, "GFT-DISC", 2, "44.00")]),
    _order(5006, "2026-09-03T09:00:00Z", [(101, "CND-VAN-200", 1, "14.00")], test=True),
]


def _inv_item(vid: int, sku: str, levels: list[tuple[int, str, int, int]]) -> dict:
    return {
        "id": f"gid://shopify/InventoryItem/{vid + 1000}",
        "sku": sku,
        "variant": {"id": f"gid://shopify/ProductVariant/{vid}"},
        "inventoryLevels": {
            "edges": [
                {
                    "node": {
                        "location": {"id": f"gid://shopify/Location/{lid}", "name": name},
                        "quantities": [
                            {"name": "available", "quantity": avail},
                            {"name": "incoming", "quantity": inc},
                        ],
                    }
                }
                for lid, name, avail, inc in levels
            ]
        },
    }


INVENTORY = [
    _inv_item(101, "CND-VAN-200", [(1, "Main Warehouse", 120, 0), (2, "FBA US", 40, 100)]),
    _inv_item(102, "CND-VAN-400", [(1, "Main Warehouse", 35, 0)]),
    _inv_item(201, "", [(1, "Main Warehouse", 300, 0)]),
    _inv_item(301, "GFT-DISC", [(1, "Main Warehouse", 18, 50)]),
]


def write(name: str, interactions: list[dict]) -> None:
    (HERE / f"{name}.yaml").write_text(
        yaml.safe_dump({"version": 1, "interactions": interactions}, sort_keys=False)
    )


def main() -> None:
    write(
        "shopify_products",
        [
            _interaction(_page("products", PRODUCTS_P1, True, "c1")),
            _interaction(_page("products", PRODUCTS_P2, False, None)),
        ],
    )
    write(
        "shopify_orders",
        [
            _interaction(_page("orders", ORDERS_P1, True, "o1")),
            _interaction(_page("orders", ORDERS_P2, False, None)),
        ],
    )
    write("shopify_inventory", [_interaction(_page("inventoryItems", INVENTORY, False, None))])
    # full sync = products (2 pages) + orders (2 pages) + inventory (1 page), in that order
    write(
        "shopify_full_sync",
        [
            _interaction(_page("products", PRODUCTS_P1, True, "c1")),
            _interaction(_page("products", PRODUCTS_P2, False, None)),
            _interaction(_page("orders", ORDERS_P1, True, "o1")),
            _interaction(_page("orders", ORDERS_P2, False, None)),
            _interaction(_page("inventoryItems", INVENTORY, False, None)),
        ],
    )
    # throttled once, then succeeds
    throttled = {
        "request": {"method": "POST", "uri": URL, "body": "<graphql>", "headers": {}},
        "response": {
            "status": {"code": 200, "message": "OK"},
            "headers": {"Content-Type": ["application/json"]},
            "body": {
                "string": json.dumps(
                    {"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]}
                )
            },
        },
    }
    write(
        "shopify_throttled", [throttled, _interaction(_page("products", PRODUCTS_P2, False, None))]
    )
    print("cassettes written to", HERE)


if __name__ == "__main__":
    main()
