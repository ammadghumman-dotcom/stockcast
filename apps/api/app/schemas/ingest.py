import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.ingest.records import IngestResult, RowError  # noqa: F401  (re-exported)
from app.models.enums import ChannelType
from app.schemas.common import Timestamped


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: ChannelType
    region_id: uuid.UUID | None = None
    external_shop_id: str | None = Field(default=None, max_length=200)


class ChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    region_id: uuid.UUID | None = None
    is_active: bool | None = None


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
