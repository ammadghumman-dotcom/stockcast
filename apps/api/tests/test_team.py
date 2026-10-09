"""Team membership and Clerk provisioning (staging bugs #1-#7)."""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import deps
from app.config import settings
from app.models import AuditLog, Organization, User
from app.services import clerk as clerk_api


# --------------------------------------------------------------------------- header mode rules
def _invite(client, headers, email, role="viewer", name="Someone"):
    return client.post("/users", json={"email": email, "name": name, "role": role}, headers=headers)


def test_invite_rules_and_owner_protection(client: TestClient, db, org, headers) -> None:
    owner = User(org_id=org.id, email="owner@example.com", name="Owner", role="owner")
    db.add(owner)
    db.flush()
    admin_h = {**headers, "X-Role": "admin"}

    assert _invite(client, admin_h, "x@example.com", role="owner").status_code == 422
    r = _invite(client, admin_h, "ada@example.com", role="admin", name="Ada")
    assert r.status_code == 201 and r.json()["status"] == "active"  # header mode: no Clerk
    ada = r.json()
    assert _invite(client, admin_h, "ADA@example.com").status_code == 409  # same email

    # an admin can neither remove the owner nor change the owner's role, nor hand out "owner"
    assert client.delete(f"/users/{owner.id}", headers=admin_h).status_code == 403
    r = client.patch(f"/users/{owner.id}", json={"role": "viewer"}, headers=admin_h)
    assert r.status_code == 403
    r = client.patch(f"/users/{ada['id']}", json={"role": "owner"}, headers=admin_h)
    assert r.status_code == 403

    # the owner can transfer ownership; the previous owner becomes admin
    owner_h = {**headers, "X-Role": "owner"}
    r = client.patch(f"/users/{ada['id']}", json={"role": "owner"}, headers=owner_h)
    assert r.status_code == 200 and r.json()["role"] == "owner"
    db.refresh(owner)
    assert owner.role == "admin"

    # admins manage other members; changes are audited
    v = _invite(client, admin_h, "vic@example.com").json()
    assert (
        client.patch(f"/users/{v['id']}", json={"role": "admin"}, headers=admin_h).json()["role"]
        == "admin"
    )
    assert client.delete(f"/users/{v['id']}", headers=admin_h).status_code == 204
    actions = {a.action for a in db.query(AuditLog).filter_by(org_id=org.id)}
    assert {"team.invite", "team.role", "team.remove"} <= actions


def test_me_reports_role(client: TestClient, headers) -> None:
    r = client.get("/me", headers={**headers, "X-Role": "viewer"})
    assert r.status_code == 200 and r.json()["role"] == "viewer"


# --------------------------------------------------------------------------- Clerk mode
@pytest.fixture
def clerk(monkeypatch):
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
    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_x")
    monkeypatch.setattr(deps, "_last_refresh", {})

    calls: list[tuple[str, str, dict | None]] = []
    users = {
        "u_owner": ("owner@example.com", "Olive"),
        "u_ada": ("ada@example.com", "Ada"),
    }

    def fake_call(method, path, json=None):
        calls.append((method, path, json))
        if method == "GET" and path.startswith("/users/"):
            email, first = users.get(path.split("/")[-1], ("", ""))
            return {
                "primary_email_address_id": "e1",
                "email_addresses": [{"id": "e1", "email_address": email}],
                "first_name": first,
                "last_name": "",
            }
        if method == "GET" and path.startswith("/organizations/"):
            return {"name": "Acme Candles", "slug": "acme", "created_by": "u_owner"}
        if path.endswith("/invitations"):
            return {"id": "orginv_1"}
        return {}

    monkeypatch.setattr(clerk_api, "_call", fake_call)

    def mint(sub="u_owner", v2=False, role="org:admin", org="org_acme", **extra) -> str:
        now = int(time.time())
        payload = {"iss": "https://clerk.test", "sub": sub, "iat": now, "exp": now + 60, **extra}
        if v2:
            payload["o"] = {"id": org, "rol": role.removeprefix("org:"), "slg": "acme"}
        else:
            payload.update(org_id=org, org_role=role)
        return jwt.encode(payload, private, algorithm="RS256", headers={"kid": "k1"})

    mint.calls = calls  # type: ignore[attr-defined]
    return mint


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def test_v2_token_claims_are_accepted_and_creator_is_owner(client, db, clerk) -> None:
    r = client.get("/me", headers=_h(clerk(v2=True)))
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["role"] == "owner" and me["email"] == "owner@example.com"
    assert me["org_name"] == "Acme Candles"
    # role stays owner on later requests although Clerk says org:admin
    assert client.get("/me", headers=_h(clerk(v2=True))).json()["role"] == "owner"


def test_invite_goes_through_clerk_and_first_sign_in_claims_the_row(client, db, clerk) -> None:
    owner = _h(clerk())
    client.get("/me", headers=owner)
    r = _invite(client, owner, "ada@example.com", role="admin", name="Ada")
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "invited"
    inv = [c for c in clerk.calls if c[1].endswith("/invitations")]
    assert (
        inv and inv[0][2]["role"] == "org:admin" and inv[0][2]["email_address"] == "ada@example.com"
    )

    # Ada accepts the invite in Clerk and signs in: her invited row is linked, not duplicated
    me = client.get("/me", headers=_h(clerk(sub="u_ada"))).json()
    assert me["role"] == "admin" and me["email"] == "ada@example.com"
    org = db.query(Organization).filter_by(clerk_org_id="org_acme").one()
    rows = db.query(User).filter_by(org_id=org.id, email="ada@example.com").all()
    assert len(rows) == 1 and rows[0].external_auth_id == "u_ada" and rows[0].status == "active"


def test_role_change_and_removal_are_written_to_clerk(client, db, clerk) -> None:
    owner = _h(clerk())
    client.get("/me", headers=owner)
    _invite(client, owner, "ada@example.com", role="admin")
    client.get("/me", headers=_h(clerk(sub="u_ada")))
    ada = next(
        u for u in client.get("/users", headers=owner).json() if u["email"].startswith("ada")
    )

    assert (
        client.patch(f"/users/{ada['id']}", json={"role": "viewer"}, headers=owner).status_code
        == 200
    )
    assert (
        "PATCH",
        "/organizations/org_acme/memberships/u_ada",
        {"role": "org:member"},
    ) in clerk.calls
    assert client.delete(f"/users/{ada['id']}", headers=owner).status_code == 204
    assert ("DELETE", "/organizations/org_acme/memberships/u_ada", None) in clerk.calls


def test_removing_a_pending_invite_revokes_it(client, db, clerk) -> None:
    owner = _h(clerk())
    client.get("/me", headers=owner)
    pending = _invite(client, owner, "new@example.com").json()
    assert client.delete(f"/users/{pending['id']}", headers=owner).status_code == 204
    assert any(c[1].endswith("/invitations/orginv_1/revoke") for c in clerk.calls)


def test_clerk_errors_surface_as_409(client, db, clerk, monkeypatch) -> None:
    owner = _h(clerk())
    client.get("/me", headers=owner)

    def refuse(*_a, **_k):
        raise clerk_api.ClerkError(422, "already a member")

    monkeypatch.setattr(clerk_api, "invite", refuse)
    r = _invite(client, owner, "dup@example.com")
    assert r.status_code == 409 and "already a member" in r.json()["detail"]


def test_team_changes_without_secret_key_explain_why(client, db, clerk, monkeypatch) -> None:
    owner = _h(clerk())
    client.get("/me", headers=owner)
    monkeypatch.setattr(settings, "clerk_secret_key", "")
    r = _invite(client, owner, "x@example.com")
    assert r.status_code == 503 and "CLERK_SECRET_KEY" in r.json()["detail"]


def test_placeholder_email_is_repaired_later(client, db, clerk, monkeypatch) -> None:
    monkeypatch.setattr(settings, "clerk_secret_key", "")
    client.get("/me", headers=_h(clerk()))
    org = db.query(Organization).filter_by(clerk_org_id="org_acme").one()
    u = db.query(User).filter_by(org_id=org.id).one()
    assert u.email.endswith(deps.PLACEHOLDER_EMAIL_DOMAIN) and org.name.startswith("Workspace ")

    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_x")
    monkeypatch.setattr(deps, "_last_refresh", {})
    client.get("/me", headers=_h(clerk()))
    db.refresh(u)
    db.refresh(org)
    assert u.email == "owner@example.com" and org.name == "Acme Candles"


def test_clock_skew_within_leeway_is_accepted(client, clerk) -> None:
    now = int(time.time())
    tok = clerk(iat=now - 70, exp=now - 10)  # expired 10 s ago, inside the 30 s leeway
    assert client.get("/me", headers=_h(tok)).status_code == 200
