from app.models import Customer, CustomerCreate, CustomerUpdate


class CustomerRepository:
    """Repositório em memória para clientes."""

    def __init__(self) -> None:
        self._items: dict[int, Customer] = {}
        self._next_id: int = 1

    def list(self) -> list[Customer]:
        return list(self._items.values())

    def get(self, customer_id: int) -> Customer | None:
        return self._items.get(customer_id)

    def create(self, payload: CustomerCreate) -> Customer:
        customer = Customer(id=self._next_id, **payload.model_dump())
        self._items[self._next_id] = customer
        self._next_id += 1
        return customer

    def update(self, customer_id: int, payload: CustomerUpdate) -> Customer | None:
        existing = self._items.get(customer_id)
        if existing is None:
            return None
        updated_data = existing.model_dump()
        for key, value in payload.model_dump(exclude_unset=True).items():
            updated_data[key] = value
        updated = Customer(**updated_data)
        self._items[customer_id] = updated
        return updated

    def deactivate(self, customer_id: int) -> Customer | None:
        return self.update(customer_id, CustomerUpdate(active=False))

    def delete(self, customer_id: int) -> bool:
        return self._items.pop(customer_id, None) is not None

    def clear(self) -> None:
        self._items.clear()
        self._next_id = 1
