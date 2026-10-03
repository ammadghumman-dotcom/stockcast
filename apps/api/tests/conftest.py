"""Test fixtures: a real Postgres (TEST_DATABASE_URL), migrated with Alembic once per session.

Each test runs inside a transaction that is rolled back, so tests never see each other's rows.
"""

import os
import uuid
from collections.abc import Generator

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from alembic import command

PLANNING_AS_OF = __import__("datetime").date(2026, 10, 1)

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/stockcast_test"
)
os.environ["DATABASE_URL"] = TEST_DB_URL  # must be set before app.config is imported
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
os.environ.setdefault("SHOPIFY_API_KEY", "test-key")
os.environ.setdefault("SHOPIFY_API_SECRET", "test-secret")
os.environ.setdefault("SHOPIFY_API_VERSION", "2025-07")

from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Organization  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(TEST_DB_URL)
    yield eng
    eng.dispose()
    command.downgrade(cfg, "base")


@pytest.fixture
def db(engine) -> Generator[Session, None, None]:
    conn = engine.connect()
    tx = conn.begin()
    session = sessionmaker(bind=conn, join_transaction_mode="create_savepoint")()
    try:
        yield session
    finally:
        session.close()
        tx.rollback()
        conn.close()


@pytest.fixture
def client(db: Session) -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_org(db: Session, slug: str) -> Organization:
    org = Organization(id=uuid.uuid4(), name=slug.title(), slug=slug)
    db.add(org)
    db.flush()
    return org


@pytest.fixture
def org(db: Session) -> Organization:
    return _make_org(db, "acme")


@pytest.fixture
def other_org(db: Session) -> Organization:
    return _make_org(db, "rival")


@pytest.fixture
def headers(org: Organization) -> dict[str, str]:
    return {"X-Org-Id": str(org.id)}


@pytest.fixture
def other_headers(other_org: Organization) -> dict[str, str]:
    return {"X-Org-Id": str(other_org.id)}


@pytest.fixture(scope="module")
def vcr_config():
    # Cassettes are replayed only; GraphQL requests all hit one URL so match on method+uri
    # and let vcrpy play interactions in recorded order.
    return {
        "record_mode": "none",
        "match_on": ["method", "uri"],
        "allow_playback_repeats": False,
        "filter_headers": ["X-Shopify-Access-Token"],
    }


@pytest.fixture(scope="module")
def vcr_cassette_dir():
    return os.path.join(os.path.dirname(__file__), "cassettes")


@pytest.fixture
def shopify_channel(db: Session, org: Organization):
    import json

    from app import crypto
    from app.models import Channel, ChannelType

    ch = Channel(
        org_id=org.id,
        name="demo-candle",
        type=ChannelType.shopify,
        external_shop_id="demo-candle.myshopify.com",
        credentials_encrypted=crypto.encrypt(
            json.dumps({"shop": "demo-candle.myshopify.com", "access_token": "shpat_test"})
        ),
    )
    db.add(ch)
    db.flush()
    return ch


# --------------------------------------------------------------------------- planning world
@pytest.fixture
def candle_world(db, org):
    """1 candle = 200 g wax + 1 jar + 1 wick; hand calc in tests/test_planning_engine.py."""
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from app.models import (
        BomLine,
        Forecast,
        ForecastRun,
        InventoryLevel,
        Location,
        Product,
        ProductType,
        Supplier,
        SupplierProduct,
    )

    oid = org.id
    loc = Location(org_id=oid, name="Main", is_default=True)
    db.add(loc)
    db.flush()
    p = {}
    for sku, name, typ, unit, cost in [
        ("CND", "Vanilla Candle", ProductType.finished, "unit", "4.20"),
        ("WAX", "Soy Wax", ProductType.raw_material, "g", "0.0045"),
        ("JAR", "Glass Jar", ProductType.raw_material, "unit", "0.65"),
        ("WICK", "Cotton Wick", ProductType.raw_material, "unit", "0.08"),
    ]:
        p[sku] = Product(
            org_id=oid, sku=sku, name=name, type=typ, unit=unit, unit_cost=Decimal(cost)
        )
        db.add(p[sku])
    db.flush()
    for comp, qty in (("WAX", 200), ("JAR", 1), ("WICK", 1)):
        db.add(
            BomLine(
                org_id=oid,
                parent_product_id=p["CND"].id,
                component_product_id=p[comp].id,
                qty_per_unit=Decimal(qty),
            )
        )
    wax_co = Supplier(
        org_id=oid,
        name="Pacific Wax",
        email="orders@pacificwax.test",
        lead_time_days=21,
        moq=25_000,
    )
    glass = Supplier(
        org_id=oid, name="ClearGlass", email="po@clearglass.test", lead_time_days=30, moq=500
    )
    db.add_all([wax_co, glass])
    db.flush()
    db.add_all(
        [
            SupplierProduct(
                org_id=oid,
                supplier_id=wax_co.id,
                product_id=p["WAX"].id,
                price=Decimal("0.004"),
                pack_size=25_000,
            ),
            SupplierProduct(
                org_id=oid,
                supplier_id=glass.id,
                product_id=p["JAR"].id,
                price=Decimal("0.60"),
                pack_size=100,
            ),
            SupplierProduct(
                org_id=oid,
                supplier_id=glass.id,
                product_id=p["WICK"].id,
                price=Decimal("0.07"),
                pack_size=1000,
            ),
        ]
    )
    for sku, qty in (("CND", 50), ("WAX", 1000), ("JAR", 30), ("WICK", 500)):
        db.add(
            InventoryLevel(
                org_id=oid, product_id=p[sku].id, location_id=loc.id, on_hand=Decimal(qty)
            )
        )
    frun = ForecastRun(
        org_id=oid, status="success", horizon_days=90, as_of=PLANNING_AS_OF, started_at=None
    )
    db.add(frun)
    db.flush()
    frun.finished_at = datetime.now(UTC)
    db.bulk_insert_mappings(
        Forecast,
        [
            {
                "run_id": frun.id,
                "org_id": oid,
                "product_id": p["CND"].id,
                "date": PLANNING_AS_OF + timedelta(days=i + 1),
                "p10": Decimal(8),
                "p50": Decimal(10),
                "p90": Decimal(10),
                "model": "autoets",
                "factor": Decimal(1),
                "event": "Black Friday" if 50 <= i < 58 else None,
            }
            for i in range(90)
        ],
    )
    db.flush()
    return {"products": p, "suppliers": {"wax": wax_co, "glass": glass}, "loc": loc}
