"""Step 8: channel credentials, OAuth connect flows, SKU mapping, per-channel forecast split."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy import func, select

from app import crypto
from app.config import settings
from app.forecast.channels import compute_channel_shares
from app.ingest.oauth_state import make_state
from app.models import (
    Channel,
    ChannelListing,
    ForecastChannelShare,
    ForecastRun,
    Product,
    ProductType,
    SalesDaily,
)
from app.routers import connect
from app.services import listings as svc
from tests.conftest import PLANNING_AS_OF


# --------------------------------------------------------------------------- channels + creds
def test_create_channel_with_credentials_is_encrypted_and_hidden(client, db, headers) -> None:
    body = {
        "name": "Woo",
        "type": "woocommerce",
        "credentials": {
            "url": "https://s.example.com",
            "consumer_key": "ck_live_abc123",
            "consumer_secret": "cs",
        },
    }
    r = client.post("/channels", json=body, headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["is_connected"] is True and "credentials" not in r.json()
    assert r.json()["external_shop_id"] == "https://s.example.com"
    ch = db.get(Channel, r.json()["id"])
    assert "ck_live_abc123" not in ch.credentials_encrypted
    assert json.loads(crypto.decrypt(ch.credentials_encrypted))["consumer_key"] == "ck_live_abc123"


def test_missing_credential_keys_rejected(client, headers) -> None:
    r = client.post(
        "/channels",
        json={"name": "Amz", "type": "amazon", "credentials": {"refresh_token": "x"}},
        headers=headers,
    )
    assert r.status_code == 422 and "marketplace_id" in r.text
    r = client.post(
        "/channels", json={"name": "csv", "type": "csv", "credentials": {"a": "b"}}, headers=headers
    )
    assert r.status_code == 422


def test_patch_credentials_requires_admin(client, db, headers) -> None:
    r = client.post("/channels", json={"name": "eBay", "type": "ebay"}, headers=headers)
    cid = r.json()["id"]
    assert r.json()["is_connected"] is False
    creds = {"refresh_token": "r", "marketplace_id": "EBAY_GB"}
    viewer = {**headers, "X-Role": "viewer"}
    assert (
        client.patch(f"/channels/{cid}", json={"credentials": creds}, headers=viewer).status_code
        == 403
    )
    r = client.patch(f"/channels/{cid}", json={"credentials": creds}, headers=headers)
    assert r.status_code == 200 and r.json()["is_connected"] is True


# --------------------------------------------------------------------------- OAuth connect
def test_amazon_install_redirects_to_seller_central(client, db, headers, monkeypatch) -> None:
    monkeypatch.setattr(settings, "amazon_app_id", "amzn1.sp.solution.test")
    ch = client.post(
        "/channels",
        json={"name": "Amz", "type": "amazon", "external_shop_id": "A1F83G8C2ARO7P"},
        headers=headers,
    ).json()
    r = client.get(f"/amazon/install?channel_id={ch['id']}", headers=headers)
    assert r.status_code == 200, r.text
    url = urlparse(r.json()["url"])
    r2 = client.get(
        f"/amazon/install?channel_id={ch['id']}&redirect=true",
        headers=headers,
        follow_redirects=False,
    )
    assert r2.status_code == 302
    assert url.netloc == "sellercentral-europe.amazon.com"  # UK marketplace -> EU consent host
    q = parse_qs(url.query)
    assert q["application_id"] == ["amzn1.sp.solution.test"] and "state" in q


def test_amazon_callback_stores_refresh_token_and_syncs(client, db, headers, monkeypatch) -> None:
    ch = client.post(
        "/channels",
        json={"name": "Amz", "type": "amazon", "external_shop_id": "ATVPDKIKX0DER"},
        headers=headers,
    ).json()
    calls: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(dict(parse_qs(req.content.decode())))
        return httpx.Response(200, json={"refresh_token": "Atzr|new", "access_token": "a"})

    monkeypatch.setattr(
        connect, "_http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr("app.routers.connect.enqueue_sync", lambda db, ch, **kw: None)
    state = make_state(o=str(db.get(Channel, ch["id"]).org_id), c=ch["id"])
    r = client.get(
        f"/amazon/callback?state={state}&spapi_oauth_code=code1&selling_partner_id=A2SELLER",
        follow_redirects=False,
    )
    assert r.status_code == 302 and r.headers["location"].endswith(f"?connected={ch['id']}")
    assert calls[0]["code"] == ["code1"]
    creds = json.loads(crypto.decrypt(db.get(Channel, ch["id"]).credentials_encrypted))
    assert creds == {
        "refresh_token": "Atzr|new",
        "marketplace_id": "ATVPDKIKX0DER",
        "seller_id": "A2SELLER",
    }


def test_callback_rejects_tampered_or_foreign_state(client, db, headers, other_org) -> None:
    ch = client.post("/channels", json={"name": "eBay", "type": "ebay"}, headers=headers).json()
    bad = make_state(o=str(other_org.id), c=ch["id"])  # valid signature, wrong org
    assert client.get(f"/ebay/callback?state={bad}&code=x").status_code == 400
    good = make_state(o=str(db.get(Channel, ch["id"]).org_id), c=ch["id"])
    tampered = good[:-2] + "zz"
    assert client.get(f"/ebay/callback?state={tampered}&code=x").status_code == 400


# --------------------------------------------------------------------------- SKU mapping
def _product(db, org_id, sku, name):
    p = Product(org_id=org_id, sku=sku, name=name, type=ProductType.finished)
    db.add(p)
    db.flush()
    return p


def _listing(db, org_id, channel_id, product_id, ext, ext_sku=None):
    row = ChannelListing(
        org_id=org_id,
        channel_id=channel_id,
        product_id=product_id,
        external_id=ext,
        external_sku=ext_sku,
    )
    db.add(row)
    db.flush()
    return row


def test_match_suggests_fuzzy_products_and_override_merges(
    client, db, org, headers, amazon_channel
):
    catalog = _product(db, org.id, "CND-VAN-200", "Vanilla Candle 200g")
    _product(db, org.id, "CND-LAV-200", "Lavender Candle 200g")
    _product(db, org.id, "OUD-10", "Oud Oil 10ml")
    # what the Amazon sync auto-created: slightly different seller SKU, Amazon-style title
    auto = _product(db, org.id, "CND_VAN_200_FBA", "Vanilla Scented Soy Candle 200 g")
    listing = _listing(db, org.id, amazon_channel.id, auto.id, "B0VAN20000", "CND_VAN_200_FBA")
    for i, units in enumerate((3, 2)):
        db.add(
            SalesDaily(
                org_id=org.id,
                product_id=auto.id,
                channel_id=amazon_channel.id,
                date=date(2026, 9, 1) + timedelta(days=i),
                units=Decimal(units),
                revenue=Decimal(0),
            )
        )
    db.flush()

    r = client.post("/listings/match", json={"channel_id": str(amazon_channel.id)}, headers=headers)
    assert r.status_code == 200, r.text
    result = r.json()[0]
    assert result["listing"]["external_id"] == "B0VAN20000"
    assert result["listing"]["product_sku"] == "CND_VAN_200_FBA"
    top = result["suggestions"][0]
    assert top["product_id"] == str(catalog.id) and top["score"] >= 85
    assert [s["sku"] for s in result["suggestions"]][:2] == ["CND-VAN-200", "CND-LAV-200"]

    # manual override: listing re-points, sales move, orphan product deleted
    r = client.post(
        f"/listings/{listing.id}/override", json={"product_id": str(catalog.id)}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "listing": {
            **result["listing"],
            "product_id": str(catalog.id),
            "product_sku": "CND-VAN-200",
            "product_name": "Vanilla Candle 200g",
            "product_listing_count": 1,
        },
        "moved_sales_rows": 2,
        "deleted_product": True,
    }
    assert db.get(Product, auto.id) is None
    total = db.scalar(select(func.sum(SalesDaily.units)).where(SalesDaily.product_id == catalog.id))
    assert total == 5
    # once mapped by hand the listing is left alone by default
    r = client.post("/listings/match", json={"channel_id": str(amazon_channel.id)}, headers=headers)
    assert r.json() == [] or r.json()[0]["listing"]["product_listing_count"] == 1
    assert (
        client.get(f"/listings?channel_id={amazon_channel.id}", headers=headers).json()[0][
            "product_sku"
        ]
        == "CND-VAN-200"
    )


def test_override_sums_into_existing_sales_rows_and_keeps_shared_product(db, org, amazon_channel):
    a = _product(db, org.id, "A", "Thing A")
    b = _product(db, org.id, "B", "Thing B")
    la = _listing(db, org.id, amazon_channel.id, a.id, "X1")
    _listing(db, org.id, amazon_channel.id, b.id, "X2")
    _listing(db, org.id, amazon_channel.id, a.id, "X1-ALT")  # a stays referenced
    for pid, units in ((a.id, 2), (b.id, 5)):
        db.add(
            SalesDaily(
                org_id=org.id,
                product_id=pid,
                channel_id=amazon_channel.id,
                date=date(2026, 9, 1),
                units=Decimal(units),
                revenue=Decimal(1),
            )
        )
    db.flush()
    res = svc.override(db, org.id, la, b.id)
    assert res == {"moved_sales_rows": 1, "deleted_product": False}
    row = db.scalar(select(SalesDaily).where(SalesDaily.product_id == b.id))
    assert row.units == 7 and row.revenue == 2
    assert db.get(Product, a.id) is not None


def test_create_listing_manually(client, db, org, headers, amazon_channel) -> None:
    p = _product(db, org.id, "P", "P")
    body = {"channel_id": str(amazon_channel.id), "product_id": str(p.id), "external_id": "X9"}
    r = client.post("/listings", json=body, headers=headers)
    assert r.status_code == 201 and r.json()["product_sku"] == "P"
    assert client.post("/listings", json=body, headers=headers).status_code == 409


def test_listing_override_is_org_scoped(client, db, headers, other_headers, amazon_channel, org):
    p = _product(db, org.id, "P", "P")
    lst = _listing(db, org.id, amazon_channel.id, p.id, "E1")
    r = client.post(
        f"/listings/{lst.id}/override", json={"product_id": str(p.id)}, headers=other_headers
    )
    assert r.status_code == 404
    r = client.get(f"/listings?channel_id={amazon_channel.id}", headers=other_headers)
    assert r.status_code in (404, 422)  # assert_owned: foreign channel is rejected, never listed


# --------------------------------------------------------------------------- channel split
def test_channel_shares_from_last_90_days(db, org, amazon_channel, ebay_channel) -> None:
    p = _product(db, org.id, "P", "P")
    q = _product(db, org.id, "Q", "Q")
    as_of = date(2026, 10, 1)
    rows = [
        (p.id, amazon_channel.id, as_of, 60),
        (p.id, ebay_channel.id, as_of - timedelta(days=10), 40),
        (p.id, ebay_channel.id, as_of - timedelta(days=100), 999),  # outside the window
        (q.id, ebay_channel.id, as_of, 0),  # zero demand -> no share rows
    ]
    for pid, cid, d, units in rows:
        db.add(
            SalesDaily(
                org_id=org.id, product_id=pid, channel_id=cid, date=d, units=units, revenue=0
            )
        )
    run = ForecastRun(org_id=org.id, as_of=as_of, status="success", horizon_days=30)
    db.add(run)
    db.flush()
    assert compute_channel_shares(db, org.id, run.id, as_of) == 2
    shares = {
        (s.channel_id, float(s.share), float(s.units_90d))
        for s in db.scalars(
            select(ForecastChannelShare).where(ForecastChannelShare.run_id == run.id)
        )
    }
    assert shares == {(amazon_channel.id, 0.6, 60.0), (ebay_channel.id, 0.4, 40.0)}
    assert compute_channel_shares(db, org.id, run.id, as_of) == 2  # idempotent (replace)


def test_product_forecast_and_recommendations_expose_channel_mix(
    client, db, org, headers, candle_world, amazon_channel, ebay_channel, monkeypatch
) -> None:
    """End to end on the candle world: forecast -> plan -> both endpoints carry the split."""
    from app.forecast.engine import run_forecast
    from app.models import PlanningRun
    from app.planning.engine import run_planning

    monkeypatch.setattr("app.forecast.router.chronos_available", lambda: False)
    candle = candle_world["products"]["CND"]
    as_of = PLANNING_AS_OF
    # 120 days of history: 10/day on eBay + 5/day on Amazon -> 2/3 vs 1/3
    for i in range(120):
        d = as_of - timedelta(days=i)
        for ch, units in ((ebay_channel, 10), (amazon_channel, 5)):
            db.add(
                SalesDaily(
                    org_id=org.id,
                    product_id=candle.id,
                    channel_id=ch.id,
                    date=d,
                    units=units,
                    revenue=0,
                )
            )
    db.flush()
    frun = ForecastRun(org_id=org.id, horizon_days=60)
    db.add(frun)
    db.flush()
    run_forecast(db, frun, as_of=as_of, use_covariates=False)
    assert frun.status == "success", frun.error

    r = client.get(f"/forecasts?product_id={candle.id}", headers=headers)
    assert r.status_code == 200, r.text
    mix = r.json()["channels"]
    assert len(mix) == 2 and mix[0]["share"] > mix[1]["share"]
    assert abs(float(mix[0]["share"]) - 2 / 3) < 0.01 and mix[1]["channel_type"] == "amazon"
    assert abs(sum(float(m["p50_90d"]) for m in mix) - float(r.json()["total_p50_90d"])) < 0.05

    prun = PlanningRun(org_id=org.id)
    db.add(prun)
    db.flush()
    run_planning(db, prun, as_of=as_of)
    recs = client.get(f"/recommendations?product_id={candle.id}", headers=headers).json()
    assert recs and [m["channel_type"] for m in recs[0]["channel_mix"]][-1] == "amazon"
    wax = candle_world["products"]["WAX"]
    raw = client.get(f"/recommendations?product_id={wax.id}", headers=headers).json()
    assert raw and raw[0]["channel_mix"] == []  # derived demand: no channel
    one = client.get(f"/recommendations/{recs[0]['id']}", headers=headers).json()
    assert len(one["channel_mix"]) == 2
