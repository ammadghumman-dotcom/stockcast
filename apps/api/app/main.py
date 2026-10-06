import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.config import settings
from app.db import engine
from app.observability import configure_logging, configure_sentry, configure_tracing
from app.ratelimit import limiter
from app.routers import (
    amazon_webhooks,
    billing,
    bom_lines,
    calendar,
    catalog_extras,
    channels,
    connect,
    feedback,
    forecasts,
    imports,
    listings,
    locations,
    onboarding,
    orgs,
    planning,
    products,
    purchase_orders,
    shopify,
    shopify_embedded,
    suppliers,
    waitlist,
)
from app.security import (
    HttpsMiddleware,
    RequestIdMiddleware,
    cors_origins,
    production_guard,
    trusted_hosts,
)

configure_logging()
configure_sentry("api")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    problems = production_guard()
    if problems:
        raise RuntimeError("refusing to start: " + "; ".join(problems))
    log.info("api starting", extra={"env": settings.env, "release": settings.release or "dev"})
    yield


app = FastAPI(title=settings.app_name, version="0.9.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
# Middleware order (outermost first): request id -> https/HSTS -> hosts -> CORS -> rate limit
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Org-Id", "X-Role", "X-Request-Id"],
    expose_headers=["X-Request-Id"],
    max_age=600,
)
if settings.allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts())
app.add_middleware(HttpsMiddleware, enabled=settings.force_https)
app.add_middleware(RequestIdMiddleware)
configure_tracing(app=app, engine=engine)

app.include_router(orgs.router)
app.include_router(products.router)
app.include_router(catalog_extras.router)
app.include_router(suppliers.router)
app.include_router(bom_lines.router)
app.include_router(locations.router)
app.include_router(channels.router)
app.include_router(imports.router)
app.include_router(listings.router)
app.include_router(shopify.router)
app.include_router(shopify_embedded.router)
app.include_router(connect.router)
app.include_router(amazon_webhooks.router)
app.include_router(forecasts.router)
app.include_router(calendar.router)
app.include_router(planning.router)
app.include_router(purchase_orders.router)
app.include_router(billing.router)
app.include_router(waitlist.router)
app.include_router(onboarding.router)
app.include_router(feedback.router)


class Health(BaseModel):
    status: str
    service: str
    version: str
    env: str
    time: datetime


@app.get("/health", response_model=Health, tags=["system"])
def health() -> Health:
    """Liveness: the process is up. Used by Railway + the uptime check."""
    return Health(
        status="ok",
        service="stockcast-api",
        version=app.version,
        env=settings.env,
        time=datetime.now(UTC),
    )


class Readiness(Health):
    database: str
    redis: str
    release: str | None = None


@app.get("/health/ready", response_model=Readiness, tags=["system"])
def ready() -> Readiness:
    """Readiness: database + broker reachable. Deploy smoke tests hit this."""
    checks = {"database": "ok", "redis": "ok"}
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
    except Exception as exc:  # pragma: no cover - exercised in smoke tests
        checks["database"] = f"error: {type(exc).__name__}"
    try:
        import redis

        redis.Redis.from_url(settings.celery_broker_url, socket_connect_timeout=2).ping()
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    body = Readiness(
        status="ok" if all(v == "ok" for v in checks.values()) else "degraded",
        service="stockcast-api",
        version=app.version,
        env=settings.env,
        time=datetime.now(UTC),
        release=settings.release or None,
        **checks,
    )
    if body.status != "ok":
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, body.model_dump(mode="json"))
    return body
