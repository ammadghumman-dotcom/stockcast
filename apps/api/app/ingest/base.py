"""Connector contract. Each sales channel implements this; the sync task drives it."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import date

from app.ingest.records import InventoryRecord, ProductRecord, SalesRecord
from app.models import Channel


class ConnectorError(RuntimeError):
    """Raised for recoverable upstream failures; the sync task retries with backoff."""


class BaseConnector(ABC):
    """A connector reads from one channel and yields normalized records.

    Implementations must be side-effect free on `fetch_*` so a retried sync re-reads safely.
    """

    supports_push: bool = False

    def __init__(self, channel: Channel) -> None:
        self.channel = channel

    @abstractmethod
    def fetch_products(self) -> Iterable[ProductRecord]: ...

    @abstractmethod
    def fetch_sales(self, since: date) -> Iterable[SalesRecord]:
        """Daily aggregated sales from `since` (inclusive) to today."""

    @abstractmethod
    def fetch_inventory(self) -> Iterable[InventoryRecord]: ...

    def push_inventory(self, records: Iterable[InventoryRecord]) -> int:
        """Write stock levels back to the channel. Optional; default is unsupported."""
        raise NotImplementedError(f"{type(self).__name__} does not support push_inventory")
