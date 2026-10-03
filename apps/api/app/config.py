from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Stockcast API"
    env: str = "development"
    database_url: str = "postgresql+psycopg://stockcast:stockcast@localhost:5432/stockcast"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:3000"
    # Fernet key for encrypting channel credentials. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    credentials_key: str = "dev-only-key-replace-me"

    # Public base URL of this API (OAuth callbacks + webhook targets must be reachable by Shopify)
    app_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"

    # Shopify Partner app (https://partners.shopify.com -> Apps -> Create app)
    shopify_api_key: str = ""
    shopify_api_secret: str = ""
    shopify_api_version: str = "2025-07"
    shopify_scopes: str = "read_products,read_orders,read_inventory,read_locations"
    shopify_backfill_days: int = 730

    # Email (Resend) for sending POs to suppliers
    resend_api_key: str = ""
    email_from: str = "Stockcast <orders@stockcast.app>"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_task_always_eager: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
