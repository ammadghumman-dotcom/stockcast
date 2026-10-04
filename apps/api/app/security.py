"""Transport security + production guard rails."""

from __future__ import annotations

from starlette.datastructures import URL
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response
from starlette.types import ASGIApp

from app.config import settings
from app.observability import new_request_id, request_id_var

HSTS = "max-age=31536000; includeSubDomains"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Honour an incoming X-Request-Id (Railway/Vercel set one) or mint one; echo it back."""

    async def dispatch(self, request, call_next):  # type: ignore[override]
        rid = request.headers.get("X-Request-Id") or new_request_id()
        token = request_id_var.set(rid)
        try:
            response: Response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-Id"] = rid
        return response


class HttpsMiddleware(BaseHTTPMiddleware):
    """Behind a TLS-terminating proxy: redirect plain http -> https and add HSTS + basic headers."""

    def __init__(self, app: ASGIApp, enabled: bool) -> None:
        super().__init__(app)
        self.enabled = enabled

    async def dispatch(self, request, call_next):  # type: ignore[override]
        if self.enabled:
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            if proto != "https" and request.url.path not in ("/health", "/health/ready"):
                url = URL(scope=request.scope).replace(scheme="https")
                return RedirectResponse(str(url), status_code=308)
        response: Response = await call_next(request)
        if self.enabled:
            response.headers["Strict-Transport-Security"] = HSTS
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


def production_guard() -> list[str]:
    """Misconfigurations that must never reach production. Returned (and raised at startup)."""
    problems: list[str] = []
    if settings.env not in ("production", "staging"):
        return problems
    if settings.auth_mode != "clerk":
        problems.append("AUTH_MODE must be 'clerk' outside development")
    if settings.credentials_key == "dev-only-key-replace-me":
        problems.append("CREDENTIALS_KEY is the dev default")
    if not settings.force_https:
        problems.append("FORCE_HTTPS must be true")
    if any(o.startswith("http://") and "localhost" not in o for o in cors_origins()):
        problems.append("CORS_ORIGINS must be https")
    if settings.billing_enabled and not settings.stripe_webhook_secret:
        problems.append("STRIPE_WEBHOOK_SECRET missing (required when STRIPE_SECRET_KEY is set)")
    return problems


def cors_origins() -> list[str]:
    return [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
