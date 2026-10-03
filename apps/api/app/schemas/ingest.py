import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.ingest.records import IngestResult, RowError  # noqa: F401  (re-exported)
from app.models.enums import ChannelType
from app.schemas.common import Timestamped

# Required credential keys per channel type when credentials are supplied directly
# (amazon/ebay can instead go through GET /amazon/install, /ebay/install).
CREDENTIAL_KEYS: dict[ChannelType, tuple[str, ...]] = {
    ChannelType.amazon: ("refresh_token", "marketplace_id"),
    ChannelType.ebay: ("refresh_token", "marketplace_id"),
    ChannelType.woocommerce: ("url", "consumer_key", "consumer_secret"),
}


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: ChannelType
    region_id: uuid.UUID | None = None
    # amazon: marketplace id (ATVPDKIKX0DER); ebay: EBAY_US; woocommerce: store url
    external_shop_id: str | None = Field(default=None, max_length=200)
    # stored encrypted, never returned; see CREDENTIAL_KEYS
    credentials: dict[str, str] | None = None


class ChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    region_id: uuid.UUID | None = None
    is_active: bool | None = None
    external_shop_id: str | None = Field(default=None, max_length=200)
    credentials: dict[str, str] | None = None


class ChannelRead(Timestamped):
    """Never exposes credentials."""

    org_id: uuid.UUID
    name: str
    type: ChannelType
    region_id: uuid.UUID | None
    external_shop_id: str | None
    is_active: bool
    is_connected: bool
    last_synced_at: datetime | None


class SyncRunRead(Timestamped):
    org_id: uuid.UUID
    channel_id: uuid.UUID
    status: str
    trigger: str
    started_at: datetime | None
    finished_at: datetime | None
    rows_products: int
    rows_sales: int
    rows_inventory: int
    error: str | None


class ImportResponse(BaseModel):
    channel_id: uuid.UUID
    results: list[IngestResult]
