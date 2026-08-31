from fastapi.testclient import TestClient

from database import profiles_table, users_table
from main import app

client = TestClient(app)


def _register_and_login(**overrides):
    payload = {
        "email": "profile.user@example.com",
        "password": "supersecure123",
        "name": "Original Name",
        "phone": "555-0100",
    }
    payload.update(overrides)
    client.post("/users", json=payload)
    login = client.post(
        "/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
    )
    token = login.json()["access_token"]
    return token, payload


def setup_function():
    users_table.truncate()
    profiles_table.truncate()


# ---- Happy path ----
def test_owner_updates_name_profile_changes_user_unchanged():
    token, _ = _register_and_login()
    headers = {"Authorization": f"Bearer {token}"}

    response = client.put(
        "/profiles/me", json={"name": "Updated Name"}, headers=headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    # Untouched field must survive the partial update.
    assert data["phone"] == "555-0100"

    # The linked User record (email) must be unaffected by a profile edit.
    me = client.get("/auth/me", headers=headers).json()
    assert me["email"] == "profile.user@example.com"


# ---- Edge case ----
def test_empty_optional_phone_is_accepted():
    token, _ = _register_and_login()
    headers = {"Authorization": f"Bearer {token}"}

    response = client.put("/profiles/me", json={"phone": ""}, headers=headers)

    assert response.status_code == 200
    assert response.json()["phone"] == ""


# ---- Failure mode ----
def test_update_profile_without_token_returns_401():
    response = client.put("/profiles/me", json={"name": "No Auth"})

    assert response.status_code == 401