from fastapi.testclient import TestClient
from tinydb import Query

from database import profiles_table, users_table
from main import app

client = TestClient(app)


def _register_payload(**overrides):
    payload = {
        "email": "test.user@example.com",
        "password": "supersecure123",
        "name": "Test User",
        "phone": "555-0100",
        "address": "123 Main St",
    }
    payload.update(overrides)
    return payload


def setup_function():
    users_table.truncate()
    profiles_table.truncate()


# ---- Happy path ----
def test_register_valid_creates_user_with_default_role_and_linked_profile():
    response = client.post("/users", json=_register_payload())
    assert response.status_code == 201

    data = response.json()
    assert data["email"] == "test.user@example.com"
    assert data["role"] == "user"
    assert data["is_active"] is True
    assert "hashed_password" not in data

    linked_profile = profiles_table.get(Query().user_id == data["id"])
    assert linked_profile is not None
    assert linked_profile["name"] == "Test User"
    assert linked_profile["phone"] == "555-0100"


# ---- Edge case ----
def test_register_duplicate_email_rejected_before_second_insert():
    client.post("/users", json=_register_payload())

    response = client.post("/users", json=_register_payload())

    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"
    # Only one user should exist in the table after the rejected duplicate.
    assert len(users_table.all()) == 1


# ---- Failure modes ----
def test_register_password_too_short_rejected_before_db_write():
    response = client.post("/users", json=_register_payload(password="short"))

    assert response.status_code == 422
    assert users_table.all() == []


def test_register_missing_email_rejected_before_db_write():
    payload = _register_payload()
    del payload["email"]

    response = client.post("/users", json=payload)

    assert response.status_code == 422
    assert users_table.all() == []