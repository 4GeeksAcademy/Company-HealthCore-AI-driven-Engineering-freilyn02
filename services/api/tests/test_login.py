from fastapi.testclient import TestClient
from jose import jwt

from app.core.security import ALGORITHM, SECRET_KEY
from database import profiles_table, users_table
from main import app

client = TestClient(app)


def _register(**overrides):
    payload = {
        "email": "login.user@example.com",
        "password": "supersecure123",
        "name": "Login User",
    }
    payload.update(overrides)
    return client.post("/users", json=payload).json()


def setup_function():
    users_table.truncate()
    profiles_table.truncate()


# ---- Happy path ----
def test_login_correct_credentials_returns_jwt_for_correct_user():
    user = _register()

    response = client.post(
        "/auth/login",
        data={"username": "login.user@example.com", "password": "supersecure123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert "access_token" in body

    decoded = jwt.decode(body["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
    assert decoded["sub"] == str(user["id"])


# ---- Edge case ----
def test_login_inactive_user_is_rejected():
    user = _register()
    users_table.update({"is_active": False}, doc_ids=[user["id"]])

    response = client.post(
        "/auth/login",
        data={"username": "login.user@example.com", "password": "supersecure123"},
    )

    assert response.status_code == 401


# ---- Failure mode ----
def test_login_wrong_password_issues_no_token():
    _register()

    response = client.post(
        "/auth/login",
        data={"username": "login.user@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert "access_token" not in response.json()