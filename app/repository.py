from app.models import Customer, CustomerCreate, CustomerUpdate


class DuplicateEmailError(ValueError):
    """Erro lançado quando um e-mail já está em uso por outro cliente."""


class CustomerRepository:
    """Repositório em memória para clientes."""

    def __init__(self) -> None:
        self._items: dict[int, Customer] = {}
        self._next_id: int = 1

    def _has_duplicate_email(self, email: str, exclude_customer_id: int | None = None) -> bool:
        normalized = email.casefold()
        return any(
            cid != exclude_customer_id and customer.email.casefold() == normalized
            for cid, customer in self._items.items()
        )

    def list(
        self,
        email: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Customer]:
        customers = list(self._items.values())
        if email is not None:
            needle = email.casefold()
            customers = [
                customer for customer in customers if needle in customer.email.casefold()
            ]
        return customers[offset : offset + limit]

    def get(self, customer_id: int) -> Customer | None:
        return self._items.get(customer_id)

    def create(self, payload: CustomerCreate) -> Customer:
        if self._has_duplicate_email(payload.email):
            raise DuplicateEmailError("Customer email already exists")
        customer = Customer(id=self._next_id, **payload.model_dump())
        self._items[self._next_id] = customer
        self._next_id += 1
        return customer

    def update(self, customer_id: int, payload: CustomerUpdate) -> Customer | None:
        existing = self._items.get(customer_id)
        if existing is None:
            return None
        updates = payload.model_dump(exclude_unset=True)
        new_email = updates.get("email")
        if new_email is not None and self._has_duplicate_email(
            new_email, exclude_customer_id=customer_id
        ):
            raise DuplicateEmailError("Customer email already exists")
        updated_data = existing.model_dump()
        for key, value in updates.items():
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
