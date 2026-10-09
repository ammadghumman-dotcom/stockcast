"""Auth: every route is org-scoped, viewers are read-only, Clerk JWTs are verified."""

from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import deps
from app.config import settings
from app.main import app
from app.models import Organization, User

# Routes that are legitimately unauthenticated: public, signed another way, or create the org.
PUBLIC = {
    ("GET", "/health"),
    ("POST", "/orgs"),
    ("GET", "/shopify/callback"),  # HMAC-signed by Shopify, carries org in `state`
    ("GET", "/amazon/callback"),  # org + channel in signed `state`
    ("GET", "/ebay/callback"),
    ("POST", "/webhooks/shopify/orders-create"),  # HMAC-signed
    ("POST", "/webhooks/shopify/inventory-levels-update"),
    ("POST", "/webhooks/shopify/app-uninstalled"),
    ("POST", "/webhooks/shopify/customers-data-request"),  # GDPR, HMAC-signed
    ("POST", "/webhooks/shopify/customers-redact"),
    ("POST", "/webhooks/shopify/shop-redact"),
    ("POST", "/webhooks/shopify/app-subscriptions-update"),  # HMAC-signed
    ("POST", "/webhooks/stripe"),  # Stripe-Signature
    ("POST", "/webhooks/amazon"),  # shared-secret HMAC
    ("GET", "/health/ready"),
    ("POST", "/waitlist"),  # public landing-page form, IP rate-limited
}


def _depends_on_auth(route: APIRoute) -> bool:
    seen = set()
    stack = list(route.dependant.dependencies)
    while stack:
        d = stack.pop()
        if d.call in (deps.get_auth, deps.get_org_id):
            return True
        if id(d) in seen:
            continue
        seen.add(id(d))
        stack.extend(d.dependencies)
    return False


def _api_routes(router) -> list[APIRoute]:
    """Walk nested routers (FastAPI keeps included routers as children)."""
    out: list[APIRoute] = []
    for r in router.routes:
        if isinstance(r, APIRoute):
            out.append(r)
        elif hasattr(r, "original_router"):  # FastAPI >= 0.140 `_IncludedRouter`
            out.extend(_api_routes(r.original_router))
        elif hasattr(r, "routes"):
            out.extend(_api_routes(r))
    return out


def test_every_route_is_org_scoped_or_allowlisted() -> None:
    """Fails the build if someone adds a route that forgets `OrgId`/`Ctx`."""
    routes = _api_routes(app)
    assert len(routes) > 40, "route walk looks broken"
    unguarded = []
    for route in routes:
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if (method, route.path) in PUBLIC:
                continue
            if not _depends_on_auth(route):
                unguarded.append(f"{method} {route.path}")
    assert unguarded == [], f"routes without org scope: {unguarded}"


def test_allowlist_has_no_stale_entries() -> None:
    paths = {(m, r.path) for r in _api_routes(app) for m in r.methods}
    assert PUBLIC <= paths


# --------------------------------------------------------------------------- roles (header mode)
def test_viewer_is_read_only(client: TestClient, headers: dict) -> None:
    viewer = {**headers, "X-Role": "viewer"}
    assert client.get("/products", headers=viewer).status_code == 200
    r = client.post("/products", json={"sku": "V", "name": "x", "type": "finished"}, headers=viewer)
    assert r.status_code == 403
    assert (
        client.patch("/planning-settings", json={"service_level": 0.9}, headers=viewer).status_code
        == 403
    )


def test_admin_required_for_user_management(client: TestClient, headers: dict) -> None:
    body = {"email": "new@example.com", "name": "New"}
    assert (
        client.post("/users", json=body, headers={**headers, "X-Role": "viewer"}).status_code == 403
    )
    assert (
        client.post("/users", json=body, headers={**headers, "X-Role": "admin"}).status_code == 201
    )


def test_bearer_token_without_clerk_config_is_503(client: TestClient, headers: dict) -> None:
    r = client.get("/products", headers={**headers, "Authorization": "Bearer abc"})
    assert r.status_code == 503


# --------------------------------------------------------------------------- Clerk JWT
@pytest.fixture
def clerk(monkeypatch):
    """Local RSA key pair + fake JWKS so tokens verify exactly like Clerk's would."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    class _Key:
        key = public_pem

    class _Jwks:
        def get_signing_key_from_jwt(self, token):
            return _Key()

    monkeypatch.setattr(deps, "_jwks_client", lambda url: _Jwks())
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://clerk.test/.well-known/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", "https://clerk.test")
    monkeypatch.setattr(settings, "clerk_secret_key", "")  # no backend lookups

    def mint(**claims) -> str:
        now = int(time.time())
        payload = {
            "iss": "https://clerk.test",
            "sub": "user_1",
            "iat": now,
            "exp": now + 300,
            "org_id": "org_abc",
            "org_role": "org:admin",
            "email": "alice@acme.test",
            "name": "Alice",
            **claims,
        }
        return jwt.encode(payload, private, algorithm="RS256", headers={"kid": "k1"})

    return mint


def test_clerk_token_provisions_org_and_user(client: TestClient, db, clerk) -> None:
    tok = clerk()
    r = client.get("/orgs/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"] == "trial" and body["trial_ends_at"] is not None
    org = db.query(Organization).filter_by(clerk_org_id="org_abc").one()
    user = db.query(User).filter_by(org_id=org.id, external_auth_id="user_1").one()
    # the first user of a new workspace is its owner (Clerk itself only knows org:admin)
    assert (user.email, user.role) == ("alice@acme.test", "owner")

    # second call: same org, same user, no duplicates
    client.get("/orgs/me", headers={"Authorization": f"Bearer {tok}"})
    assert db.query(Organization).filter_by(clerk_org_id="org_abc").count() == 1
    assert db.query(User).filter_by(external_auth_id="user_1").count() == 1


def test_clerk_orgs_are_isolated(client: TestClient, clerk) -> None:
    a = {"Authorization": f"Bearer {clerk(org_id='org_a', sub='u_a')}"}
    b = {"Authorization": f"Bearer {clerk(org_id='org_b', sub='u_b')}"}
    created = client.post(
        "/products", json={"sku": "P", "name": "p", "type": "finished"}, headers=a
    )
    assert created.status_code == 201, created.text
    assert client.get(f"/products/{created.json()['id']}", headers=b).status_code == 404
    assert client.get("/products", headers=b).json() == []
    # X-Org-Id is ignored when a Bearer token is present: no header-based org switching
    hijack = {**b, "X-Org-Id": str(uuid.uuid4())}
    assert client.get("/products", headers=hijack).json() == []


def test_clerk_member_role_is_viewer(client: TestClient, clerk) -> None:
    h = {"Authorization": f"Bearer {clerk(org_role='org:member', org_id='org_m', sub='u_m')}"}
    assert client.get("/products", headers=h).status_code == 200
    r = client.post("/products", json={"sku": "P", "name": "p", "type": "finished"}, headers=h)
    assert r.status_code == 403


def test_clerk_token_without_org_is_403(client: TestClient, clerk) -> None:
    r = client.get("/products", headers={"Authorization": f"Bearer {clerk(org_id=None)}"})
    assert r.status_code == 403


def test_bad_signature_expired_and_wrong_issuer_are_401(client: TestClient, clerk) -> None:
    good = clerk()
    tampered = good[:-4] + ("AAAA" if not good.endswith("AAAA") else "BBBB")
    assert (
        client.get("/products", headers={"Authorization": f"Bearer {tampered}"}).status_code == 401
    )
    expired = clerk(exp=int(time.time()) - 60)
    assert (
        client.get("/products", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    )
    wrong_iss = clerk(iss="https://evil.test")
    assert (
        client.get("/products", headers={"Authorization": f"Bearer {wrong_iss}"}).status_code == 401
    )
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(jwt.decode(good, options={"verify_signature": False}), other_key, "RS256")
    assert client.get("/products", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_clerk_mode_rejects_header_auth(client: TestClient, headers: dict, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "clerk")
    assert client.get("/products", headers=headers).status_code == 401
