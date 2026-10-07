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
    shopify_api_version: str = "2026-07"
    # App handle in the Shopify admin URL (admin.shopify.com/store/<shop>/apps/<handle>)
    shopify_app_handle: str = "stockcast"
    # Billing API test charges (dev stores always get test charges regardless)
    shopify_billing_test: bool = False
    shopify_scopes: str = "read_products,read_orders,read_all_orders,read_inventory,read_locations"
    shopify_backfill_days: int = 730

    # Auth: "clerk" verifies Clerk session JWTs; "header" trusts X-Org-Id (dev / e2e only)
    auth_mode: str = "header"
    clerk_jwks_url: str = ""  # https://<your-frontend-api>.clerk.accounts.dev/.well-known/jwks.json
    clerk_issuer: str = ""  # https://<your-frontend-api>.clerk.accounts.dev
    clerk_secret_key: str = ""  # used to fetch org/user names on first sight (optional)

    # Amazon SP-API (Login with Amazon app credentials) + eBay developer app
    amazon_lwa_client_id: str = ""
    amazon_lwa_client_secret: str = ""
    amazon_app_id: str = ""  # SP-API application id for the Seller Central consent URL
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_ru_name: str = ""  # eBay "RuName" (redirect URL name) registered for the app

    # Rate limiting (slowapi); memory:// in tests
    rate_limit_enabled: bool = True
    rate_limit_storage: str = "redis://localhost:6379/2"
    rate_limit_default: str = "600/minute"
    rate_limit_heavy: str = "30/minute"

    # Billing (Stripe)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_growth: str = ""
    stripe_price_scale: str = ""
    trial_days: int = 14

    @property
    def billing_enabled(self) -> bool:
        """Billing is on only when a payment provider is configured. Without it (e.g. a Stripe
        account isn't available in the founder's country) the app runs with trials that never lock,
        and checkout/portal return 503."""
        return bool(self.stripe_secret_key)

    # Email (Resend) for sending POs to suppliers and transactional mail
    resend_api_key: str = ""
    email_from: str = "Stockcast <orders@stockcast.app>"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_task_always_eager: bool = False

    # Observability (Step 9)
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1
    release: str = ""  # git sha, set by the deploy workflow
    log_format: str = "json"  # json | text
    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: str = (
        ""  # e.g. https://otlp-gateway-prod-eu-west-2.grafana.net/otlp
    )
    otel_exporter_otlp_headers: str = ""  # "Authorization=Basic <base64 instanceId:token>"
    otel_service_name: str = "stockcast-api"
    # Alerts: Sentry message + optional webhook (Slack incoming webhook / Grafana OnCall)
    alert_webhook_url: str = ""
    # Product analytics (PostHog). Empty key = events are only recorded as milestones in the db.
    posthog_api_key: str = ""
    posthog_host: str = "https://us.i.posthog.com"
    # Weekly activation cohort report recipients (comma-separated); also posted to the alert hook
    report_emails: str = ""
    alert_sync_failure_rate: float = 0.05  # over the last 24 h
    alert_forecast_max_minutes: int = 30
    # Security
    force_https: bool = False  # redirect http -> https and send HSTS (set in staging/prod)
    allowed_hosts: str = ""  # comma list for TrustedHostMiddleware; empty = any
    amazon_webhook_secret: str = (
        ""  # shared secret for POST /webhooks/amazon (EventBridge API dest.)
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
