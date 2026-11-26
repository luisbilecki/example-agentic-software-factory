from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app, repository


@pytest.fixture(autouse=True)
def reset_repository() -> Iterator[None]:
    repository.clear()
    yield
    repository.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_healthcheck(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_crud_customer_lifecycle(client: TestClient) -> None:
    # Create
    created = client.post(
        "/customers",
        json={"name": "Ada Lovelace", "email": "ada@example.com", "active": True},
    )
    assert created.status_code == 201
    customer = created.json()
    assert customer["id"] == 1
    assert customer["name"] == "Ada Lovelace"

    # List
    listed = client.get("/customers")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    # Get
    fetched = client.get("/customers/1")
    assert fetched.status_code == 200
    assert fetched.json()["email"] == "ada@example.com"

    # Update
    updated = client.put("/customers/1", json={"name": "Augusta Ada", "active": False})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Augusta Ada"
    assert updated.json()["active"] is False

    # Delete
    deleted = client.delete("/customers/1")
    assert deleted.status_code == 204

    # Not found after delete
    missing = client.get("/customers/1")
    assert missing.status_code == 404


def test_deactivate_customer(client: TestClient) -> None:
    created = client.post(
        "/customers",
        json={"name": "Grace Hopper", "email": "grace@example.com", "active": True},
    )
    assert created.status_code == 201
    customer_id = created.json()["id"]

    deactivated = client.patch(f"/customers/{customer_id}/deactivate")
    assert deactivated.status_code == 200
    assert deactivated.json() == {
        "id": customer_id,
        "name": "Grace Hopper",
        "email": "grace@example.com",
        "active": False,
    }

    fetched = client.get(f"/customers/{customer_id}")
    assert fetched.status_code == 200
    assert fetched.json()["active"] is False

    # Idempotente quando já está inativo
    deactivated_again = client.patch(f"/customers/{customer_id}/deactivate")
    assert deactivated_again.status_code == 200
    assert deactivated_again.json()["active"] is False


def test_not_found_errors(client: TestClient) -> None:
    assert client.get("/customers/999").status_code == 404
    assert client.put("/customers/999", json={"name": "Ghost"}).status_code == 404
    assert client.patch("/customers/999/deactivate").status_code == 404
    assert client.delete("/customers/999").status_code == 404
