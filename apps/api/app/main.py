from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
from app.routers import (
    bom_lines,
    calendar,
    catalog_extras,
    channels,
    forecasts,
    imports,
    locations,
    orgs,
    planning,
    products,
    purchase_orders,
    shopify,
    suppliers,
)

app = FastAPI(title=settings.app_name, version="0.6.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orgs.router)
app.include_router(products.router)
app.include_router(catalog_extras.router)
app.include_router(suppliers.router)
app.include_router(bom_lines.router)
app.include_router(locations.router)
app.include_router(channels.router)
app.include_router(imports.router)
app.include_router(shopify.router)
app.include_router(forecasts.router)
app.include_router(calendar.router)
app.include_router(planning.router)
app.include_router(purchase_orders.router)


class Health(BaseModel):
    status: str
    service: str
    version: str
    env: str
    time: datetime


@app.get("/health", response_model=Health, tags=["system"])
def health() -> Health:
    return Health(
        status="ok",
        service="stockcast-api",
        version=app.version,
        env=settings.env,
        time=datetime.now(UTC),
    )
