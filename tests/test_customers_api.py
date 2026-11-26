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


def test_not_found_errors(client: TestClient) -> None:
    assert client.get("/customers/999").status_code == 404
    assert client.put("/customers/999", json={"name": "Ghost"}).status_code == 404
    assert client.delete("/customers/999").status_code == 404


def test_create_customer_duplicate_email_returns_409(client: TestClient) -> None:
    first = client.post(
        "/customers",
        json={"name": "Ada Lovelace", "email": "ada@example.com"},
    )
    assert first.status_code == 201

    duplicate_exact = client.post(
        "/customers",
        json={"name": "Another Ada", "email": "ada@example.com"},
    )
    assert duplicate_exact.status_code == 409
    assert duplicate_exact.json() == {"detail": "Customer email already exists"}

    duplicate_case_insensitive = client.post(
        "/customers",
        json={"name": "Upper Ada", "email": "ADA@EXAMPLE.COM"},
    )
    assert duplicate_case_insensitive.status_code == 409
    assert duplicate_case_insensitive.json() == {"detail": "Customer email already exists"}


def test_update_customer_duplicate_email_returns_409(client: TestClient) -> None:
    c1 = client.post(
        "/customers",
        json={"name": "Ada Lovelace", "email": "ada@example.com"},
    ).json()
    c2 = client.post(
        "/customers",
        json={"name": "Grace Hopper", "email": "grace@example.com"},
    ).json()

    conflict = client.put(
        f"/customers/{c2['id']}",
        json={"email": "ADA@example.com"},
    )
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "Customer email already exists"}

    # Ensure customer 2 was not modified
    fetched = client.get(f"/customers/{c2['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["email"] == "grace@example.com"

    # Updating the same customer keeping their own email (same or different case) succeeds
    same_email = client.put(
        f"/customers/{c1['id']}",
        json={"name": "Augusta Ada", "email": "Ada@Example.com"},
    )
    assert same_email.status_code == 200
    assert same_email.json()["name"] == "Augusta Ada"
    assert same_email.json()["email"] == "Ada@Example.com"
