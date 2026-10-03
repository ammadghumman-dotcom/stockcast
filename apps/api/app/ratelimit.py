"""Per-org rate limiting (slowapi + Redis).

Key = org id when the request is authenticated (set by deps.get_auth on request.state), else the
client IP. Storage comes from RATE_LIMIT_STORAGE (redis://... in prod, memory:// in tests).
Set RATE_LIMIT_ENABLED=false to switch it off (e2e, local scripts).
"""

from __future__ import annotations

import jwt
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings


def org_or_ip(request: Request) -> str:
    """Runs in middleware, before auth: read the org from the (unverified) token or header.

    Using unverified claims is fine for a *bucket key* — a forged token is rejected by
    `get_auth` anyway, and at worst an attacker spreads their requests across more buckets.
    """
    auth = getattr(request.state, "auth", None)
    if auth is not None:
        return f"org:{auth.org_id}"
    bearer = request.headers.get("Authorization", "")
    if bearer.startswith("Bearer "):
        try:
            claims = jwt.decode(bearer[7:], options={"verify_signature": False})
            key = claims.get("org_id") or claims.get("sub")
            if key:
                return f"org:{key}"
        except jwt.PyJWTError:
            pass
    org = request.headers.get("X-Org-Id")
    if org:
        return f"org:{org}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(
    key_func=org_or_ip,
    storage_uri=settings.rate_limit_storage,
    default_limits=[settings.rate_limit_default],
    enabled=settings.rate_limit_enabled,
    headers_enabled=False,  # True requires every decorated route to return a Response
    in_memory_fallback_enabled=True,  # Redis down -> degrade to per-process limits, not 500s
)

heavy = limiter.limit(settings.rate_limit_heavy)  # decorate imports, forecasts, exports
