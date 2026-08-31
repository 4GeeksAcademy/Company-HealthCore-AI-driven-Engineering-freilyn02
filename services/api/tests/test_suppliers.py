from fastapi.testclient import TestClient

from database import suppliers_table
from main import app

client = TestClient(app)


def _create_payload(**overrides):
    payload = {
        "name": "Test Supplier",
        "country": "US",
        "categories": ["Medical Equipment"],
        "rate": 100.0,
    }
    payload.update(overrides)
    return payload


def setup_function():
    suppliers_table.truncate()


def test_create_supplier_valid():
    response = client.post("/suppliers", json=_create_payload())
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Supplier"
    assert data["status"] == "active"
    assert "updated_at" in data
    assert "id" in data


def test_create_supplier_invalid_status_rejected():
    response = client.post("/suppliers", json=_create_payload(status="unknown"))
    assert response.status_code == 422


def test_create_supplier_invalid_rate_rejected():
    assert client.post("/suppliers", json=_create_payload(rate=-5)).status_code == 422
    assert client.post("/suppliers", json=_create_payload(rate=0)).status_code == 422


def test_list_suppliers_filters_by_country_and_category():
    client.post("/suppliers", json=_create_payload(name="US Supplier", country="US", categories=["Lab Supplies"]))
    client.post("/suppliers", json=_create_payload(name="UK Supplier", country="UK", categories=["Pharmaceuticals"]))

    us_only = client.get("/suppliers", params={"country": "US"}).json()
    assert all(s["country"] == "US" for s in us_only)
    assert any(s["name"] == "US Supplier" for s in us_only)

    lab_only = client.get("/suppliers", params={"category": "Lab Supplies"}).json()
    assert all("Lab Supplies" in s["categories"] for s in lab_only)


def test_get_supplier_not_found_returns_404():
    assert client.get("/suppliers/999999").status_code == 404


def test_patch_rate_not_found_returns_404():
    assert client.patch("/suppliers/999999/rate", json={"rate": 50}).status_code == 404


def test_delete_not_found_returns_404():
    assert client.delete("/suppliers/999999").status_code == 404


def test_patch_rate_updates_updated_at():
    created = client.post("/suppliers", json=_create_payload()).json()
    original_updated_at = created["updated_at"]

    patched = client.patch(f"/suppliers/{created['id']}/rate", json={"rate": 250.0})
    assert patched.status_code == 200
    data = patched.json()
    assert data["rate"] == 250.0
    assert data["updated_at"] != original_updated_at


def test_patch_status_invalid_value_rejected():
    created = client.post("/suppliers", json=_create_payload()).json()
    response = client.patch(f"/suppliers/{created['id']}/status", json={"status": "archived"})
    assert response.status_code == 422


def test_delete_supplier_removes_it():
    created = client.post("/suppliers", json=_create_payload()).json()
    assert client.delete(f"/suppliers/{created['id']}").status_code == 204
    assert client.get(f"/suppliers/{created['id']}").status_code == 404


def test_seeder_is_idempotent():
    import seed

    seed.main()
    count_after_first_run = len(suppliers_table.all())

    seed.main()
    count_after_second_run = len(suppliers_table.all())

    assert count_after_first_run == count_after_second_run