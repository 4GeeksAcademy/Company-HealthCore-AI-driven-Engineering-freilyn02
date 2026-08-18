from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from jose import jwt

from app.core.security import ALGORITHM, SECRET_KEY, create_access_token
from database import profiles_table, users_table
from main import app

client = TestClient(app)


def _register_and_login(**overrides):
    payload = {
        "email": "token.user@example.com",
        "password": "supersecure123",
        "name": "Token User",
    }
    payload.update(overrides)
    user = client.post("/users", json=payload).json()
    login = client.post(
        "/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
    )
    return user, login.json()["access_token"]


def setup_function():
    users_table.truncate()
    profiles_table.truncate()


# ---- Happy path ----
def test_valid_token_identifies_user_on_auth_me():
    user, token = _register_and_login()

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "token.user@example.com"
    assert data["profile"]["name"] == "Token User"


# ---- Edge case ----
def test_token_near_expiry_still_succeeds_before_expiry():
    user, _ = _register_and_login()
    # A freshly issued token, even one minute before expiry, must still work.
    near_expiry_token = create_access_token({"sub": str(user["id"])})

    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {near_expiry_token}"}
    )

    assert response.status_code == 200


# ---- Failure modes ----
def test_expired_token_returns_401_with_no_user():
    user, _ = _register_and_login()
    expired_payload = {
        "sub": str(user["id"]),
        "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
    }
    expired_token = jwt.encode(expired_payload, SECRET_KEY, algorithm=ALGORITHM)

    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
    )

    assert response.status_code == 401
    assert "email" not in response.json()


def test_malformed_token_returns_401():
    response = client.get(
        "/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )

    assert response.status_code == 401


def test_missing_token_returns_401():
    response = client.get("/auth/me")

    assert response.status_code == 401