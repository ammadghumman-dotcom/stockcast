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
