from fastapi import FastAPI, HTTPException, Query, Response, status

from app.models import Customer, CustomerCreate, CustomerUpdate
from app.repository import CustomerRepository

app = FastAPI(title="Customers CRUD API", version="0.1.0")
repository = CustomerRepository()


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/customers", response_model=list[Customer])
def list_customers(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[Customer]:
    return repository.list(limit=limit, offset=offset)


@app.get("/customers/{customer_id}", response_model=Customer)
def get_customer(customer_id: int) -> Customer:
    customer = repository.get(customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@app.post("/customers", response_model=Customer, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerCreate) -> Customer:
    return repository.create(payload)


@app.put("/customers/{customer_id}", response_model=Customer)
def update_customer(customer_id: int, payload: CustomerUpdate) -> Customer:
    customer = repository.update(customer_id, payload)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@app.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(customer_id: int) -> Response:
    deleted = repository.delete(customer_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
