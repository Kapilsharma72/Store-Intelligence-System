"""
Unit tests for app/auth.py — JWT authentication middleware.

Covers:
  - POST /api/v1/auth/login  (Requirement 17.1)
  - POST /api/v1/auth/refresh (Requirement 17.2)
  - get_current_user dependency (Requirements 17.3, 17.4)
  - JWT payload claims (sub, role, exp)
"""

import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt

# Ensure a predictable secret during tests
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_ALGORITHM", "HS256")

from app.auth import (
    JWT_ALGORITHM,
    JWT_SECRET,
    _create_access_token,
    _decode_token,
    get_current_user,
    router as auth_router,
)
from fastapi import FastAPI, Depends
from app.auth import UserContext


# ---------------------------------------------------------------------------
# Minimal test app that mounts only the auth router
# ---------------------------------------------------------------------------

test_app = FastAPI()
test_app.include_router(auth_router)


# A protected endpoint to exercise get_current_user
@test_app.get("/protected")
def protected(user: UserContext = Depends(get_current_user)):
    return {"username": user.username, "role": user.role}


@pytest.fixture
def client():
    with TestClient(test_app) as c:
        yield c


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_token(client, username="admin", password="admin123"):
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Login endpoint tests
# ---------------------------------------------------------------------------

class TestLogin:
    def test_admin_login_returns_token(self, client):
        resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    def test_user_login_returns_token(self, client):
        resp = client.post("/api/v1/auth/login", json={"username": "user", "password": "user123"})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_wrong_password_returns_401(self, client):
        resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401

    def test_unknown_user_returns_401(self, client):
        resp = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
        assert resp.status_code == 401

    def test_token_contains_sub_claim(self, client):
        token = _get_token(client, "admin", "admin123")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["sub"] == "admin"

    def test_token_contains_role_claim_admin(self, client):
        token = _get_token(client, "admin", "admin123")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["role"] == "admin"

    def test_token_contains_role_claim_user(self, client):
        token = _get_token(client, "user", "user123")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["role"] == "user"

    def test_token_exp_is_24_hours_from_now(self, client):
        before = datetime.now(timezone.utc)
        token = _get_token(client, "admin", "admin123")
        after = datetime.now(timezone.utc)
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        # exp should be ~24 h from now (allow 5-second tolerance)
        assert exp >= before + timedelta(hours=24) - timedelta(seconds=5)
        assert exp <= after + timedelta(hours=24) + timedelta(seconds=5)


# ---------------------------------------------------------------------------
# Refresh endpoint tests
# ---------------------------------------------------------------------------

class TestRefresh:
    def test_refresh_returns_new_token(self, client):
        token = _get_token(client)
        resp = client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    def test_refresh_preserves_role(self, client):
        token = _get_token(client, "user", "user123")
        resp = client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": f"Bearer {token}"},
        )
        new_token = resp.json()["access_token"]
        payload = jwt.decode(new_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["role"] == "user"

    def test_refresh_without_token_returns_401(self, client):
        resp = client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401

    def test_refresh_with_invalid_token_returns_401(self, client):
        resp = client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": "Bearer not.a.valid.token"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# get_current_user dependency tests (via /protected endpoint)
# ---------------------------------------------------------------------------

class TestGetCurrentUser:
    def test_valid_token_grants_access(self, client):
        token = _get_token(client)
        resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "admin"
        assert body["role"] == "admin"

    def test_missing_token_returns_401(self, client):
        resp = client.get("/protected")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client):
        resp = client.get("/protected", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 401

    def test_expired_token_returns_401(self, client):
        # Manually craft an already-expired token
        payload = {
            "sub": "admin",
            "role": "admin",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        expired_token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        resp = client.get("/protected", headers={"Authorization": f"Bearer {expired_token}"})
        assert resp.status_code == 401

    def test_token_missing_role_claim_returns_401(self, client):
        # Token without role claim
        payload = {
            "sub": "admin",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_token_missing_sub_claim_returns_401(self, client):
        payload = {
            "role": "admin",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Internal helper unit tests
# ---------------------------------------------------------------------------

class TestCreateAndDecodeToken:
    def test_round_trip(self):
        token = _create_access_token("alice", "admin")
        payload = _decode_token(token)
        assert payload["sub"] == "alice"
        assert payload["role"] == "admin"

    def test_wrong_secret_raises_401(self):
        token = jwt.encode(
            {"sub": "alice", "role": "user", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            "wrong-secret",
            algorithm=JWT_ALGORITHM,
        )
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _decode_token(token)
        assert exc_info.value.status_code == 401
