from __future__ import annotations

from app.ingest.base import BaseConnector
from app.ingest.csv_connector import CsvConnector
from app.ingest.shopify.connector import ShopifyConnector
from app.models import Channel, ChannelType

_REGISTRY: dict[ChannelType, type[BaseConnector]] = {
    ChannelType.csv: CsvConnector,
    ChannelType.shopify: ShopifyConnector,
}


def connector_for(channel: Channel) -> BaseConnector:
    try:
        cls = _REGISTRY[channel.type]
    except KeyError as exc:
        raise NotImplementedError(f"No connector for channel type {channel.type}") from exc
    return cls(channel)
