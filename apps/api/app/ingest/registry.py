from __future__ import annotations

from app.ingest.amazon.connector import AmazonConnector
from app.ingest.base import BaseConnector
from app.ingest.csv_connector import CsvConnector
from app.ingest.ebay.connector import EbayConnector
from app.ingest.shopify.connector import ShopifyConnector
from app.ingest.woocommerce.connector import WooCommerceConnector
from app.models import Channel, ChannelType

_REGISTRY: dict[ChannelType, type[BaseConnector]] = {
    ChannelType.csv: CsvConnector,
    ChannelType.shopify: ShopifyConnector,
    ChannelType.amazon: AmazonConnector,
    ChannelType.ebay: EbayConnector,
    ChannelType.woocommerce: WooCommerceConnector,
}


def connector_for(channel: Channel) -> BaseConnector:
    try:
        cls = _REGISTRY[channel.type]
    except KeyError as exc:
        raise NotImplementedError(f"No connector for channel type {channel.type}") from exc
    return cls(channel)
