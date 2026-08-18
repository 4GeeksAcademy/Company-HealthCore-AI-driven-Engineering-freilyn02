from fastapi.testclient import TestClient

from database import profiles_table, users_table
from main import app

client = TestClient(app)


def _register_and_login(**overrides):
    payload = {
        "email": "manage.user@example.com",
        "password": "supersecure123",
        "name": "Manage User",
    }
    payload.update(overrides)
    user = client.post("/users", json=payload).json()
    login = client.post(
        "/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
    )
    token = login.json()["access_token"]
    return user, token


def setup_function():
    users_table.truncate()
    profiles_table.truncate()


# ---- GET /users ----
def test_list_users_returns_all_authenticated():
    _register_and_login(email="one@example.com")
    _, token_two = _register_and_login(email="two@example.com")

    response = client.get("/users", headers={"Authorization": f"Bearer {token_two}"})

    assert response.status_code == 200
    emails = [u["email"] for u in response.json()]
    assert "one@example.com" in emails
    assert "two@example.com" in emails


def test_list_users_without_token_returns_401():
    assert client.get("/users").status_code == 401


# ---- GET /users/{id} ----
def test_get_user_not_found_returns_404():
    _, token = _register_and_login()

    response = client.get(
        "/users/999999", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404


# ---- PUT /users/{id} ----
def test_owner_updates_own_email():
    user, token = _register_and_login()
    headers = {"Authorization": f"Bearer {token}"}

    response = client.put(
        f"/users/{user['id']}", json={"email": "new.email@example.com"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["email"] == "new.email@example.com"


def test_non_owner_non_admin_cannot_update_another_user():
    victim, _ = _register_and_login(email="victim@example.com")
    _, attacker_token = _register_and_login(email="attacker@example.com")
    headers = {"Authorization": f"Bearer {attacker_token}"}

    response = client.put(
        f"/users/{victim['id']}",
        json={"email": "hijacked@example.com"},
        headers=headers,
    )

    assert response.status_code == 403


def test_non_admin_cannot_change_own_role():
    user, token = _register_and_login()
    headers = {"Authorization": f"Bearer {token}"}

    response = client.put(
        f"/users/{user['id']}", json={"role": "admin"}, headers=headers
    )

    assert response.status_code == 403


def test_admin_can_change_another_users_role():
    target, _ = _register_and_login(email="target@example.com")
    admin_user, admin_token = _register_and_login(email="admin@example.com")
    # Promote the second registered user to admin directly in the DB —
    # there is no public endpoint that grants the first admin role.
    users_table.update({"role": "admin"}, doc_ids=[admin_user["id"]])
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = client.put(
        f"/users/{target['id']}", json={"role": "manager"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["role"] == "manager"


# ---- DELETE /users/{id} ----
def test_owner_deletes_own_account_and_linked_profile():
    user, token = _register_and_login()
    headers = {"Authorization": f"Bearer {token}"}

    response = client.delete(f"/users/{user['id']}", headers=headers)

    assert response.status_code == 204
    assert users_table.get(doc_id=user["id"]) is None


def test_delete_user_not_found_returns_404():
    # Must be an admin: a non-owner, non-admin caller gets 403 for the
    # permission check before the route ever looks up the target user.
    admin_user, admin_token = _register_and_login(email="admin@example.com")
    users_table.update({"role": "admin"}, doc_ids=[admin_user["id"]])
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = client.delete("/users/999999", headers=headers)

    assert response.status_code == 404