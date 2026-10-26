from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.routes import auth as auth_routes
from app.auth import permissions, security
from app.auth.seed import DEMO_USERS, demo_password, ensure_users
from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.real_auth
client = TestClient(app)

ADMIN, MANAGER, ANALYST = (u[0] for u in DEMO_USERS)


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)  # keeps the generated JWT secret out of the repo
    auth_routes._failures.clear()
    ensure_users()


def login(email, password=None, **kw):
    return client.post("/api/auth/login", json={"email": email, "password": password or demo_password(), **kw})


def hdr(email):
    return {"Authorization": f"Bearer {login(email).json()['access_token']}"}


def test_password_hashing():
    h = security.hash_password("a-long-enough-password")
    assert h.startswith("scrypt$") and "a-long-enough-password" not in h
    assert security.verify_password("a-long-enough-password", h) and not security.verify_password("wrong", h)
    assert security.hash_password("a-long-enough-password") != h  # salted
    assert not security.verify_password("x", "garbage")


def test_seed_is_idempotent():
    assert ensure_users() == 0


def test_api_requires_authentication_but_health_is_public():
    assert client.get("/api/health").status_code == 200
    for path in ("/api/dashboard/status", "/api/forecast/options", "/api/risk/summary", "/api/settings", "/api/audit", "/api/users"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/recommendations/generate").status_code == 401


def test_login_success_me_and_bad_credentials():
    r = login(MANAGER, remember=True)
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "Manager" and "approve_actions" in body["user"]["capabilities"] and "manage_users" not in body["user"]["capabilities"]
    assert body["expires_in"] == 30 * 86400 and login(MANAGER).json()["expires_in"] == settings.token_hours * 3600
    assert "password" not in str(body).lower().replace("password_hash", "") or "password_hash" not in body["user"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}).json()
    assert me["email"] == MANAGER

    bad_pw, unknown = login(MANAGER, "wrong-password"), login("nobody@example.com", "whatever-password")
    assert bad_pw.status_code == unknown.status_code == 401 and bad_pw.json() == unknown.json()  # no user enumeration


def test_invalid_expired_and_tampered_tokens_are_rejected():
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    expired = jwt.encode({"sub": "1", "role": "Admin", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, security.jwt_secret(), algorithm="HS256")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    forged = jwt.encode({"sub": "1", "role": "Admin", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "not-the-secret", algorithm="HS256")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    none_alg = jwt.encode({"sub": "1"}, key=None, algorithm="none")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {none_alg}"}).status_code == 401


def test_token_role_claim_is_not_trusted():
    """A valid token for the Analyst cannot be used to claim Admin rights: the role comes from the database."""
    t = login(ANALYST).json()["access_token"]
    claims = jwt.decode(t, security.jwt_secret(), algorithms=["HS256"])
    forged = jwt.encode({**claims, "role": "Admin"}, security.jwt_secret(), algorithm="HS256")
    assert client.get("/api/users", headers={"Authorization": f"Bearer {forged}"}).status_code == 403


def test_analyst_is_read_only():
    h = hdr(ANALYST)
    assert client.get("/api/dashboard/status", headers=h).status_code == 200
    assert client.get("/api/settings", headers=h).status_code == 200
    for method, path, body in [("post", "/api/recommendations/generate", None), ("patch", "/api/recommendations/1", {"status": "Approved"}),
                               ("post", "/api/recommendations/bulk", {"ids": [1], "status": "Approved"}), ("patch", "/api/risk/alerts/1", {"status": "Resolved"}),
                               ("post", "/api/risk/scan", None), ("post", "/api/forecast/retrain", None), ("put", "/api/settings/risk", {"z_threshold": 4}),
                               ("put", "/api/settings/inventory", {"lead_time_days": 4}), ("post", "/api/settings/reset", None),
                               ("get", "/api/audit", None), ("get", "/api/audit/verify", None), ("get", "/api/users", None)]:
        r = getattr(client, method)(path, headers=h, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (method, path, r.status_code)
        assert "not permitted" in r.json()["detail"]


def test_manager_can_act_but_not_change_risk_thresholds_or_users():
    h = hdr(MANAGER)
    assert client.patch("/api/recommendations/999", headers=h, json={"status": "Approved"}).status_code == 404  # authorised, just no such row
    assert client.put("/api/settings/inventory", headers=h, json={"lead_time_days": 4}).status_code == 200
    assert client.put("/api/settings/risk", headers=h, json={"z_threshold": 4}).status_code == 403
    assert client.post("/api/settings/reset", headers=h).status_code == 403
    assert client.get("/api/audit", headers=h).status_code == 200
    assert client.get("/api/users", headers=h).status_code == 403
    assert client.post("/api/users", headers=h, json={"email": "x@y.com", "full_name": "X Y", "role": "Admin", "password": "long-enough-pass"}).status_code == 403


def test_audit_trail_names_the_real_user_and_ip():
    client.put("/api/settings/inventory", headers=hdr(MANAGER), json={"lead_time_days": 5})
    entries = client.get("/api/audit", headers=hdr(ADMIN)).json()["entries"]
    mine = next(e for e in entries if "lead_time_days" in e["action"])
    assert mine["user"] == "Priya Sharma" and mine["role"] == "Manager" and mine["ip"]
    assert any(e["action"] == "Signed in" and e["category"] == "auth" for e in entries)
    assert client.get("/api/audit/verify", headers=hdr(ADMIN)).json()["ok"]


def test_admin_user_management_rules():
    h = hdr(ADMIN)
    new = {"email": "New.User@Example.com", "full_name": "New User", "role": "Analyst", "password": "a-strong-password"}
    r = client.post("/api/users", headers=h, json=new)
    assert r.status_code == 201 and r.json()["email"] == "new.user@example.com" and "password" not in str(r.json())
    uid = r.json()["id"]
    assert client.post("/api/users", headers=h, json=new).status_code == 409
    assert client.post("/api/users", headers=h, json={**new, "email": "b@example.com", "password": "short"}).status_code == 422
    assert client.post("/api/users", headers=h, json={**new, "email": "c@example.com", "role": "Root"}).status_code == 422

    assert login("new.user@example.com", "a-strong-password").status_code == 200
    assert client.patch(f"/api/users/{uid}", headers=h, json={"role": "Manager"}).json()["role"] == "Manager"
    assert client.patch(f"/api/users/{uid}", headers=h, json={"active": False}).json()["active"] is False
    assert login("new.user@example.com", "a-strong-password").status_code == 401  # deactivated accounts cannot sign in

    me = client.get("/api/auth/me", headers=h).json()
    assert client.patch(f"/api/users/{me['id']}", headers=h, json={"active": False}).status_code == 409
    assert client.patch(f"/api/users/{me['id']}", headers=h, json={"role": "Manager"}).status_code == 409  # last admin
    assert client.patch("/api/users/9999", headers=h, json={"active": True}).status_code == 404


def test_deactivated_users_existing_token_stops_working():
    admin_h = hdr(ADMIN)
    analyst = login(ANALYST).json()
    uid = analyst["user"]["id"]
    ah = {"Authorization": f"Bearer {analyst['access_token']}"}
    assert client.get("/api/dashboard/status", headers=ah).status_code == 200
    client.patch(f"/api/users/{uid}", headers=admin_h, json={"active": False})
    assert client.get("/api/dashboard/status", headers=ah).status_code == 401


def test_lockout_after_repeated_failures():
    for _ in range(auth_routes.MAX_FAILURES):
        assert login(MANAGER, "wrong-password").status_code == 401
    blocked = login(MANAGER)  # even the right password is refused while locked out
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers
    assert login(ANALYST).status_code == 200  # other accounts are unaffected


def test_change_password():
    h = hdr(MANAGER)
    assert client.post("/api/auth/change-password", headers=h, json={"current_password": "nope", "new_password": "a-brand-new-password"}).status_code == 403
    assert client.post("/api/auth/change-password", headers=h, json={"current_password": demo_password(), "new_password": "short"}).status_code == 422
    assert client.post("/api/auth/change-password", headers=h, json={"current_password": demo_password(), "new_password": "a-brand-new-password"}).status_code == 200
    assert login(MANAGER).status_code == 401 and login(MANAGER, "a-brand-new-password").status_code == 200


def test_personas_follow_demo_mode(monkeypatch):
    p = client.get("/api/auth/personas").json()["personas"]
    assert [x["role"] for x in p] == ["Admin", "Manager", "Analyst"]
    monkeypatch.setattr(settings, "demo_mode", False)
    assert client.get("/api/auth/personas").json() == {"personas": []}


def test_permission_matrix_is_consistent():
    assert permissions.can("Admin", "manage_users") and not permissions.can("Manager", "manage_users") and not permissions.can("Analyst", "approve_actions")
    rows = {r["key"]: r for r in permissions.matrix()}
    assert rows["modify_thresholds"]["manager"] == "locked" and rows["view"]["analyst"] is True and rows["approve_actions"]["analyst"] is False
