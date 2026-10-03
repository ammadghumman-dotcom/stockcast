from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
