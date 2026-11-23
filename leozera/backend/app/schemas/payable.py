import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.finance import _empty_to_none, _positive_money_before, _strip

PayableStatus = Literal["open", "overdue", "paid", "archived"]


class ObligationCreate(BaseModel):
    description: str = Field(min_length=1, max_length=160)
    expected_amount: Decimal
    due_on: date
    category_id: uuid.UUID | None = None

    @field_validator("description", mode="before")
    @classmethod
    def strip_description(cls, value: object) -> object:
        return _strip(value)

    @field_validator("expected_amount", mode="before")
    @classmethod
    def validate_amount(cls, value: Any) -> Decimal:
        return _positive_money_before(value)


class ObligationUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=160)
    expected_amount: Decimal | None = None
    due_on: date | None = None
    category_id: uuid.UUID | None = None

    @field_validator("description", mode="before")
    @classmethod
    def strip_description(cls, value: object) -> object:
        if value is None:
            return None
        return _strip(value)

    @field_validator("expected_amount", mode="before")
    @classmethod
    def validate_amount(cls, value: Any) -> Any:
        if value is None:
            return None
        return _positive_money_before(value)


class SettlementPublic(BaseModel):
    id: uuid.UUID
    obligation_id: uuid.UUID
    entry_id: uuid.UUID
    allocated_amount: str
    released_at: datetime | None
    entry_deleted_at: datetime | None
    entry_occurred_on: date
    entry_account_id: uuid.UUID
    created_at: datetime


class ObligationPublic(BaseModel):
    id: uuid.UUID
    description: str
    expected_amount: str
    due_on: date
    category_id: uuid.UUID | None
    category_name: str | None
    status: PayableStatus
    archived_at: datetime | None
    active_settlement_id: uuid.UUID | None
    paid_amount: str | None
    created_at: datetime
    updated_at: datetime


class ObligationDetail(ObligationPublic):
    settlements: list[SettlementPublic]


class ObligationPage(BaseModel):
    items: list[ObligationPublic]
    next_cursor: str | None


class PayableSummary(BaseModel):
    open_expected: str
    overdue_expected: str
    paid_amount: str


class PaymentCreate(BaseModel):
    account_id: uuid.UUID
    amount: Decimal | None = None
    category_id: uuid.UUID | None = None
    occurred_on: date | None = None
    description: str | None = Field(default=None, max_length=500)

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, value: Any) -> Any:
        if value is None:
            return None
        return _positive_money_before(value)

    @field_validator("description", mode="before")
    @classmethod
    def clean_description(cls, value: object) -> object:
        return _empty_to_none(value)


class PaymentPublic(BaseModel):
    obligation: ObligationDetail
    entry_id: uuid.UUID
    settlement_id: uuid.UUID
    amount: str
    replayed: bool
