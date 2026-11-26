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


def test_list_customers_pagination(client: TestClient) -> None:
    for i in range(1, 6):
        response = client.post(
            "/customers",
            json={"name": f"Customer {i}", "email": f"customer{i}@example.com", "active": True},
        )
        assert response.status_code == 201

    page_1 = client.get("/customers", params={"limit": 2, "offset": 0})
    assert page_1.status_code == 200
    assert [c["id"] for c in page_1.json()] == [1, 2]

    page_2 = client.get("/customers", params={"limit": 2, "offset": 2})
    assert page_2.status_code == 200
    assert [c["id"] for c in page_2.json()] == [3, 4]

    page_3 = client.get("/customers", params={"limit": 2, "offset": 4})
    assert page_3.status_code == 200
    assert [c["id"] for c in page_3.json()] == [5]

    empty_page = client.get("/customers", params={"limit": 2, "offset": 10})
    assert empty_page.status_code == 200
    assert empty_page.json() == []


def test_list_customers_pagination_defaults_and_limits(client: TestClient) -> None:
    for i in range(1, 106):
        response = client.post(
            "/customers",
            json={"name": f"Customer {i}", "email": f"customer{i}@example.com", "active": True},
        )
        assert response.status_code == 201

    default_response = client.get("/customers")
    assert default_response.status_code == 200
    default_items = default_response.json()
    assert len(default_items) == 50
    assert default_items[0]["id"] == 1
    assert default_items[-1]["id"] == 50

    min_limit = client.get("/customers", params={"limit": 1, "offset": 0})
    assert min_limit.status_code == 200
    assert len(min_limit.json()) == 1
    assert min_limit.json()[0]["id"] == 1

    max_limit = client.get("/customers", params={"limit": 100, "offset": 0})
    assert max_limit.status_code == 200
    assert len(max_limit.json()) == 100
    assert max_limit.json()[-1]["id"] == 100


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": -1},
        {"limit": 101},
        {"offset": -1},
        {"limit": 0, "offset": -5},
    ],
)
def test_list_customers_pagination_invalid_params(
    client: TestClient, params: dict[str, int]
) -> None:
    response = client.get("/customers", params=params)
    assert response.status_code == 422
