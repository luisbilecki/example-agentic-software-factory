from pydantic import BaseModel, Field


class CustomerBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, description="Nome do cliente")
    email: str = Field(..., min_length=3, max_length=255, description="E-mail do cliente")
    active: bool = Field(default=True, description="Indica se o cliente está ativo")


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    active: bool | None = None


class Customer(CustomerBase):
    id: int
