from enum import StrEnum


class ChannelType(StrEnum):
    shopify = "shopify"
    amazon = "amazon"
    ebay = "ebay"
    woocommerce = "woocommerce"
    csv = "csv"


class ProductType(StrEnum):
    finished = "finished"
    raw_material = "raw_material"
    bundle = "bundle"


class POStatus(StrEnum):
    draft = "draft"
    sent = "sent"
    received = "received"


class HolidaySource(StrEnum):
    builtin = "builtin"
    custom = "custom"


class PromotionType(StrEnum):
    paid_ads = "paid_ads"
    discount = "discount"
    email = "email"


class PromotionScope(StrEnum):
    all = "all"
    category = "category"
    skus = "skus"
