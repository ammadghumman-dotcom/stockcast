# ruff: noqa: E501
"""Generate vcrpy cassettes for the Amazon, eBay and WooCommerce connectors.

Synthesized from the documented response shapes (SP-API Orders/Reports/FBA Inventory/Catalog,
eBay Sell Fulfillment/Inventory, WooCommerce REST v3) — there is no seller account in CI.
Tests replay them with match_on=[method, host, path] in recorded order, so query strings and
request bodies are free to vary. To re-record for real: delete the yaml, set the credentials,
run pytest with --record-mode=once.

Run:  uv run python -m tests.cassettes.make_rest_cassettes
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

HERE = Path(__file__).parent
AMZ = "https://sellingpartnerapi-na.amazon.com"
LWA = "https://api.amazon.com/auth/o2/token"
EBAY = "https://api.ebay.com"
WOO = "https://shop.example.com/wp-json/wc/v3"
S3 = "https://tortuga-prod-na.s3.amazonaws.com/report-doc-1"


def _i(method: str, uri: str, body, status: int = 200, headers: dict | None = None) -> dict:
    text = body if isinstance(body, str) else json.dumps(body)
    return {
        "request": {"method": method, "uri": uri, "body": None, "headers": {}},
        "response": {
            "status": {"code": status, "message": "OK"},
            "headers": {"Content-Type": ["application/json"], **(headers or {})},
            "body": {"string": text},
        },
    }


def write(name: str, interactions: list[dict]) -> None:
    (HERE / f"{name}.yaml").write_text(
        yaml.safe_dump({"version": 1, "interactions": interactions}, sort_keys=False)
    )


# --------------------------------------------------------------------------- Amazon
LWA_OK = _i("POST", LWA, {"access_token": "Atza|test", "token_type": "bearer", "expires_in": 3600})


def _report_flow(report_id: str, doc_id: str, tsv: str, *, polls: int = 2) -> list[dict]:
    out = [_i("POST", f"{AMZ}/reports/2021-06-30/reports", {"reportId": report_id}, 202)]
    for n in range(polls):
        status = "DONE" if n == polls - 1 else ("IN_QUEUE" if n == 0 else "IN_PROGRESS")
        body = {"reportId": report_id, "processingStatus": status}
        if status == "DONE":
            body["reportDocumentId"] = doc_id
        out.append(_i("GET", f"{AMZ}/reports/2021-06-30/reports/{report_id}", body))
    out.append(
        _i(
            "GET",
            f"{AMZ}/reports/2021-06-30/documents/{doc_id}",
            {"reportDocumentId": doc_id, "url": S3},
        )
    )
    out.append(_i("GET", S3, tsv, headers={"Content-Type": ["text/plain"]}))
    return out


LISTINGS_TSV = "\n".join(
    [
        "item-name\titem-description\tlisting-id\tseller-sku\tprice\tquantity\topen-date\t"
        "asin1\tfulfillment-channel\tstatus",
        "Vanilla Candle 200g\t\t0901A\tCND-VAN-200\t14.00\t40\t2025-01-01\tB0VAN20000\tAMAZON_NA\tActive",
        "\t\t0902A\tCND-VAN-400\t24.00\t12\t2025-01-01\tB0VAN40000\tAMAZON_NA\tActive",
        "Oud Oil 10ml\t\t0903A\tOUD-10\t18.00\t0\t2025-02-01\tB0OUD10000\tDEFAULT\tActive",
        "\t\t0904A\t\t0\t0\t\t\t\t",  # junk row without SKU
    ]
)
CATALOG = {
    "numberOfResults": 1,
    "items": [
        {
            "asin": "B0VAN40000",
            "summaries": [
                {
                    "marketplaceId": "ATVPDKIKX0DER",
                    "itemName": "Vanilla Candle 400g (Catalog)",
                    "productType": "CANDLE",
                }
            ],
        }
    ],
}

ORDERS_TSV = "\n".join(
    [
        "amazon-order-id\tmerchant-order-id\tpurchase-date\tlast-updated-date\torder-status\t"
        "fulfillment-channel\tsales-channel\tsku\tasin\titem-status\tquantity\tcurrency\titem-price",
        "111-1\t\t2026-09-01T10:00:00+00:00\t\tShipped\tAFN\tAmazon.com\tCND-VAN-200\tB0VAN20000\tShipped\t2\tUSD\t28.00",
        "111-2\t\t2026-09-01T18:30:00+00:00\t\tShipped\tAFN\tAmazon.com\tCND-VAN-200\tB0VAN20000\tShipped\t1\tUSD\t14.00",
        "111-3\t\t2026-09-02T09:00:00+00:00\t\tCancelled\tAFN\tAmazon.com\tOUD-10\tB0OUD10000\tCancelled\t1\tUSD\t18.00",
        "111-4\t\t2026-09-02T12:00:00+00:00\t\tPending\tAFN\tAmazon.com\tOUD-10\tB0OUD10000\tPending\t3\tUSD\t54.00",
        "111-5\t\t2026-09-03T12:00:00+00:00\t\tUnshipped\tMFN\tAmazon.com\tCND-VAN-400\tB0VAN40000\tUnshipped\t1\tUSD\t24.00",
    ]
)


def _order(oid: str, when: str, status: str) -> dict:
    return {
        "AmazonOrderId": oid,
        "PurchaseDate": when,
        "OrderStatus": status,
        "MarketplaceId": "ATVPDKIKX0DER",
        "OrderTotal": {"CurrencyCode": "USD", "Amount": "0"},
    }


def _item(sku: str, asin: str, qty: int, price: str) -> dict:
    return {
        "ASIN": asin,
        "SellerSKU": sku,
        "OrderItemId": f"oi-{sku}",
        "QuantityOrdered": qty,
        "ItemPrice": {"CurrencyCode": "USD", "Amount": price},
    }


ORDERS_API = [
    _i(
        "GET",
        f"{AMZ}/orders/v0/orders",
        {
            "payload": {
                "Orders": [
                    _order("222-1", "2026-10-01T15:00:00Z", "Shipped"),
                    _order("222-2", "2026-10-01T16:00:00Z", "Canceled"),
                ],
                "NextToken": "tok2",
            }
        },
    ),
    _i(
        "GET",
        f"{AMZ}/orders/v0/orders",
        {"payload": {"Orders": [_order("222-3", "2026-10-02T08:00:00Z", "Unshipped")]}},
    ),
    _i(
        "GET",
        f"{AMZ}/orders/v0/orders/222-1/orderItems",
        {
            "payload": {
                "OrderItems": [
                    _item("CND-VAN-200", "B0VAN20000", 2, "28.00"),
                    _item("OUD-10", "B0OUD10000", 1, "18.00"),
                ]
            }
        },
    ),
    _i(
        "GET",
        f"{AMZ}/orders/v0/orders/222-3/orderItems",
        {"payload": {"OrderItems": [_item("CND-VAN-400", "B0VAN40000", 3, "72.00")]}},
    ),
]


def _summary(sku: str, asin: str, fulfillable: int, working: int, shipped: int, recv: int) -> dict:
    return {
        "asin": asin,
        "fnSku": f"X00{asin[-4:]}",
        "sellerSku": sku,
        "condition": "NewItem",
        "productName": sku,
        "totalQuantity": fulfillable + working + shipped + recv,
        "inventoryDetails": {
            "fulfillableQuantity": fulfillable,
            "inboundWorkingQuantity": working,
            "inboundShippedQuantity": shipped,
            "inboundReceivingQuantity": recv,
        },
    }


FBA = [
    _i(
        "GET",
        f"{AMZ}/fba/inventory/v1/summaries",
        {
            "pagination": {"nextToken": "p2"},
            "payload": {
                "granularity": {"granularityType": "Marketplace", "granularityId": "ATVPDKIKX0DER"},
                "inventorySummaries": [
                    _summary("CND-VAN-200", "B0VAN20000", 40, 50, 30, 20),
                    _summary("CND-VAN-400", "B0VAN40000", 12, 0, 0, 0),
                ],
            },
        },
    ),
    _i(
        "GET",
        f"{AMZ}/fba/inventory/v1/summaries",
        {"payload": {"inventorySummaries": [_summary("OUD-10", "B0OUD10000", 0, 0, 0, 0)]}},
    ),
]

# --------------------------------------------------------------------------- eBay
EBAY_TOKEN = _i(
    "POST",
    f"{EBAY}/identity/v1/oauth2/token",
    {"access_token": "v^1.1#test", "expires_in": 7200, "token_type": "User Access Token"},
)


def _inv_item(sku: str, title: str, qty: int) -> dict:
    return {
        "sku": sku,
        "locale": "en_US",
        "product": {"title": title},
        "availability": {"shipToLocationAvailability": {"quantity": qty}},
    }


EBAY_INVENTORY = [
    _i(
        "GET",
        f"{EBAY}/sell/inventory/v1/inventory_item",
        {
            "total": 3,
            "size": 2,
            "limit": 2,
            "inventoryItems": [
                _inv_item("CND-VAN-200", "Vanilla Soy Candle 200g", 15),
                _inv_item("OUD-10", "Oud Perfume Oil 10ml", 4),
            ],
        },
    ),
    _i(
        "GET",
        f"{EBAY}/sell/inventory/v1/inventory_item",
        {
            "total": 3,
            "size": 1,
            "limit": 2,
            "inventoryItems": [_inv_item("SET-DISC", "Discovery Set", 0)],
        },
    ),
]


def _ebay_order(oid: str, when: str, lines: list[tuple[str, int, str]], **extra) -> dict:
    return {
        "orderId": oid,
        "creationDate": when,
        "orderPaymentStatus": extra.get("pay", "PAID"),
        "cancelStatus": {"cancelState": extra.get("cancel", "NONE_REQUESTED")},
        "lineItems": [
            {
                "lineItemId": f"li-{sku}",
                "legacyItemId": "1234567890",
                "sku": sku,
                "quantity": qty,
                "lineItemCost": {"value": cost, "currency": "USD"},
            }
            for sku, qty, cost in lines
        ],
    }


EBAY_ORDERS = [
    _i(
        "GET",
        f"{EBAY}/sell/fulfillment/v1/order",
        {
            "total": 4,
            "orders": [
                _ebay_order("01-1", "2026-09-01T09:00:00.000Z", [("CND-VAN-200", 2, "28.00")]),
                _ebay_order("01-2", "2026-09-01T20:00:00.000Z", [("OUD-10", 1, "18.00")]),
                _ebay_order(
                    "01-3", "2026-09-02T10:00:00.000Z", [("OUD-10", 5, "90.00")], cancel="CANCELED"
                ),
                _ebay_order(
                    "01-4", "2026-09-03T10:00:00.000Z", [("SET-DISC", 1, "35.00")], pay="PENDING"
                ),
            ],
        },
    ),
]

# --------------------------------------------------------------------------- WooCommerce
WOO_PRODUCTS = [
    _i(
        "GET",
        f"{WOO}/products",
        [
            {
                "id": 10,
                "name": "Vanilla Candle",
                "sku": "",
                "type": "variable",
                "status": "publish",
                "manage_stock": False,
                "categories": [{"id": 1, "name": "Candles"}],
            },
            {
                "id": 20,
                "name": "Oud Oil 10ml",
                "sku": "OUD-10",
                "type": "simple",
                "status": "publish",
                "manage_stock": True,
                "stock_quantity": 7,
                "categories": [{"id": 2, "name": "Perfume Oils"}],
            },
        ],
        headers={"X-WP-TotalPages": ["1"], "X-WP-Total": ["2"]},
    ),
    _i(
        "GET",
        f"{WOO}/products/10/variations",
        [
            {
                "id": 11,
                "sku": "CND-VAN-200",
                "manage_stock": True,
                "stock_quantity": 25,
                "attributes": [{"name": "Size", "option": "200g"}],
            },
            {
                "id": 12,
                "sku": "",
                "manage_stock": True,
                "stock_quantity": 3,
                "attributes": [{"name": "Size", "option": "400g"}],
            },
        ],
        headers={"X-WP-TotalPages": ["1"]},
    ),
]
WOO_ORDERS = [
    _i(
        "GET",
        f"{WOO}/orders",
        [
            {
                "id": 500,
                "status": "completed",
                "date_created_gmt": "2026-09-01T11:00:00",
                "line_items": [
                    {
                        "product_id": 10,
                        "variation_id": 11,
                        "sku": "CND-VAN-200",
                        "quantity": 2,
                        "total": "28.00",
                    },
                    {
                        "product_id": 20,
                        "variation_id": 0,
                        "sku": "OUD-10",
                        "quantity": 1,
                        "total": "18.00",
                    },
                ],
            },
        ],
        headers={"X-WP-TotalPages": ["2"]},
    ),
    _i(
        "GET",
        f"{WOO}/orders",
        [
            {
                "id": 501,
                "status": "processing",
                "date_created_gmt": "2026-09-02T11:00:00",
                "line_items": [
                    {
                        "product_id": 10,
                        "variation_id": 12,
                        "sku": "",
                        "quantity": 1,
                        "total": "24.00",
                    }
                ],
            }
        ],
        headers={"X-WP-TotalPages": ["2"]},
    ),
]


def main() -> None:
    write(
        "amazon_products",
        [
            LWA_OK,
            *_report_flow("rep-listings", "doc-listings", LISTINGS_TSV, polls=3),
            _i("GET", f"{AMZ}/catalog/2022-04-01/items", CATALOG),
        ],
    )
    write("amazon_orders_report", [LWA_OK, *_report_flow("rep-orders", "doc-orders", ORDERS_TSV)])
    write("amazon_orders_api", [LWA_OK, *ORDERS_API])
    write("amazon_inventory", [LWA_OK, *FBA])
    write(
        "amazon_throttled",
        [
            LWA_OK,
            _i(
                "GET",
                f"{AMZ}/fba/inventory/v1/summaries",
                {"errors": [{"code": "QuotaExceeded"}]},
                429,
                headers={"Retry-After": ["1"]},
            ),
            FBA[1],
        ],
    )
    write("ebay_products", [EBAY_TOKEN, *EBAY_INVENTORY])
    write("ebay_orders", [EBAY_TOKEN, *EBAY_ORDERS])
    write("ebay_inventory", [EBAY_TOKEN, *EBAY_INVENTORY])
    write("woo_products", WOO_PRODUCTS)
    write("woo_orders", WOO_ORDERS)
    write("woo_inventory", WOO_PRODUCTS)
    one_sync = [
        LWA_OK,
        *_report_flow("rep-listings", "doc-listings", LISTINGS_TSV, polls=1),
        _i("GET", f"{AMZ}/catalog/2022-04-01/items", CATALOG),
        *_report_flow("rep-orders", "doc-orders", ORDERS_TSV, polls=1),
        *FBA,
    ]
    write("amazon_full_sync", one_sync * 2)  # the test syncs twice to prove idempotency
    write("ebay_full_sync", [EBAY_TOKEN, *EBAY_INVENTORY, *EBAY_ORDERS, *EBAY_INVENTORY])
    write("woo_full_sync", [*WOO_PRODUCTS, *WOO_ORDERS, *WOO_PRODUCTS])


if __name__ == "__main__":
    main()
