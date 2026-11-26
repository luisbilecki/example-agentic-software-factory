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


def test_list_customers_filter_by_email(client: TestClient) -> None:
    client.post(
        "/customers",
        json={"name": "Ada Lovelace", "email": "Ada.Lovelace@Example.com", "active": True},
    )
    client.post(
        "/customers",
        json={"name": "Grace Hopper", "email": "grace@navy.mil", "active": True},
    )
    client.post(
        "/customers",
        json={"name": "Alan Turing", "email": "alan@example.com", "active": False},
    )

    # Sem filtro retorna todos os clientes
    all_response = client.get("/customers")
    assert all_response.status_code == 200
    assert len(all_response.json()) == 3

    # Busca parcial case-insensitive
    domain_response = client.get("/customers", params={"email": "EXAMPLE.COM"})
    assert domain_response.status_code == 200
    assert [c["name"] for c in domain_response.json()] == ["Ada Lovelace", "Alan Turing"]

    partial_response = client.get("/customers", params={"email": "lovelace"})
    assert partial_response.status_code == 200
    assert [c["email"] for c in partial_response.json()] == ["Ada.Lovelace@Example.com"]

    # Sem correspondência retorna lista vazia
    empty_response = client.get("/customers", params={"email": "naoexiste@test.com"})
    assert empty_response.status_code == 200
    assert empty_response.json() == []
