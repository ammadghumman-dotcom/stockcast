"""Structured logging, Sentry and OpenTelemetry. Everything is opt-in via env vars so tests
and local dev stay quiet; production sets SENTRY_DSN, OTEL_EXPORTER_OTLP_ENDPOINT, LOG_FORMAT.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

from pythonjsonlogger.json import JsonFormatter

from app.config import settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_configured = False


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.env = settings.env
        record.service = settings.otel_service_name
        return True


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format == "json":
        handler.setFormatter(
            JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s %(env)s %(service)s",
                rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
            )
        )
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
        )
    handler.addFilter(_ContextFilter())
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel("WARNING")
    _configured = True


def configure_sentry(component: str) -> None:
    if not settings.sentry_dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.env,
        release=settings.release or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,  # no emails / IPs / request bodies
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            SqlalchemyIntegration(),
            CeleryIntegration(monitor_beat_tasks=True),
        ],
    )
    sentry_sdk.set_tag("component", component)


def configure_tracing(app: Any = None, engine: Any = None) -> None:
    """OTLP/HTTP traces (Grafana Cloud Tempo). No-op without an endpoint."""
    if not settings.otel_exporter_otlp_endpoint:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    headers = dict(
        kv.split("=", 1) for kv in settings.otel_exporter_otlp_headers.split(",") if "=" in kv
    )
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.otel_service_name,
                "deployment.environment": settings.env,
                "service.version": settings.release or "dev",
            }
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces",
                headers=headers,
            )
        )
    )
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()
    CeleryInstrumentor().instrument()
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="health,health/ready")
    if engine is not None:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(engine=engine)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def alert(title: str, detail: dict[str, Any], *, level: str = "error") -> None:
    """Raise an operational alert: Sentry event + optional webhook (Slack-compatible JSON)."""
    log = logging.getLogger("stockcast.alerts")
    log.log(logging.ERROR if level == "error" else logging.WARNING, title, extra={"alert": detail})
    if settings.sentry_dsn:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            scope.set_context("alert", detail)
            sentry_sdk.capture_message(title, level=level)  # type: ignore[arg-type]
    if settings.alert_webhook_url:
        import httpx

        lines = "\n".join(f"• {k}: {v}" for k, v in detail.items())
        try:
            httpx.post(
                settings.alert_webhook_url,
                json={"text": f"[{settings.env}] {title}\n{lines}"},
                timeout=10,
            )
        except httpx.HTTPError:
            log.exception("alert webhook failed")
