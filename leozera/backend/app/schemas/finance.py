import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

TWOPLACES = Decimal("0.01")
MONEY_LIMIT = Decimal("9999999999999.99")
CATEGORY_GROUPS: frozenset[str] = frozenset()

EntryKind = Literal["income", "expense", "transfer", "adjustment"]


def ensure_money(value: Any, *, positive: bool = False) -> Decimal:
    """Aceita string, inteiro ou Decimal com no máximo duas casas significativas.

    Trailing zeros não contam como escala extra. ``float`` é recusado porque a
    conversão binária não é uma representação decimal confiável. O valor é
    quantizado para duas casas só depois dessa verificação, quando a operação
    é exata.
    """

    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("Informe o valor como string decimal com até duas casas.")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError("Informe o valor monetário.")
        try:
            amount = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError("Valor monetário inválido.") from exc
    else:
        raise ValueError("Valor monetário inválido.")

    if not amount.is_finite():
        raise ValueError("Valor monetário inválido.")

    exponent = amount.normalize().as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise ValueError("Use no máximo duas casas decimais.")

    quantized = amount.quantize(TWOPLACES)
    if quantized < -MONEY_LIMIT or quantized > MONEY_LIMIT:
        raise ValueError("Valor monetário fora do limite.")
    if positive and quantized <= 0:
        raise ValueError("O valor deve ser maior que zero.")
    return quantized


def format_money(value: Decimal) -> str:
    return format(Decimal(value).quantize(TWOPLACES), "f")


def _strip(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


def _empty_to_none(value: object) -> object:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def _money_before(value: Any) -> Decimal:
    return ensure_money(value)


def _positive_money_before(value: Any) -> Decimal:
    return ensure_money(value, positive=True)


def _group_code(value: object) -> object:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Grupo de categoria inválido.")
    stripped = value.strip()
    if not stripped:
        return None
    if stripped not in CATEGORY_GROUPS:
        raise ValueError("Grupo de categoria indisponível.")
    return stripped


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    initial_balance: Decimal = Decimal("0.00")
    opened_on: date | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return _strip(value)

    @field_validator("initial_balance", mode="before")
    @classmethod
    def validate_initial_balance(cls, value: Any) -> Decimal:
        return _money_before(value)


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    initial_balance: Decimal | None = None
    opened_on: date | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return _strip(value)

    @field_validator("initial_balance", mode="before")
    @classmethod
    def validate_initial_balance(cls, value: Any) -> Any:
        if value is None:
            return None
        return _money_before(value)


class AccountPublic(BaseModel):
    id: uuid.UUID
    name: str
    initial_balance: str
    opened_on: date
    is_default: bool
    archived_at: datetime | None
    balance: str
    created_at: datetime
    updated_at: datetime


class BalancePublic(BaseModel):
    account_id: uuid.UUID
    as_of: date
    balance: str
    income_total: str
    expense_total: str


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    group_code: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return _strip(value)

    @field_validator("group_code", mode="before")
    @classmethod
    def validate_group(cls, value: object) -> object:
        return _group_code(value)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    group_code: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return _strip(value)

    @field_validator("group_code", mode="before")
    @classmethod
    def validate_group(cls, value: object) -> object:
        return _group_code(value)


class CategoryPublic(BaseModel):
    id: uuid.UUID
    name: str
    group_code: str | None
    code: str | None
    is_internal: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TransactionCreate(BaseModel):
    account_id: uuid.UUID
    category_id: uuid.UUID
    kind: Literal["income", "expense"]
    amount: Decimal
    occurred_on: date
    description: str | None = Field(default=None, max_length=500)

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, value: Any) -> Decimal:
        return _positive_money_before(value)

    @field_validator("description", mode="before")
    @classmethod
    def clean_description(cls, value: object) -> object:
        return _empty_to_none(value)


class TransactionUpdate(BaseModel):
    account_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    amount: Decimal | None = None
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


class TransferCreate(BaseModel):
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Decimal
    occurred_on: date
    description: str | None = Field(default=None, max_length=500)

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, value: Any) -> Decimal:
        return _positive_money_before(value)

    @field_validator("description", mode="before")
    @classmethod
    def clean_description(cls, value: object) -> object:
        return _empty_to_none(value)


class TransferUpdate(BaseModel):
    from_account_id: uuid.UUID | None = None
    to_account_id: uuid.UUID | None = None
    amount: Decimal | None = None
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


class AdjustmentCreate(BaseModel):
    balance: Decimal
    occurred_on: date
    description: str | None = Field(default=None, max_length=500)

    @field_validator("balance", mode="before")
    @classmethod
    def validate_balance(cls, value: Any) -> Decimal:
        return _money_before(value)

    @field_validator("description", mode="before")
    @classmethod
    def clean_description(cls, value: object) -> object:
        return _empty_to_none(value)


class AdjustmentUpdate(BaseModel):
    balance: Decimal | None = None
    occurred_on: date | None = None
    description: str | None = Field(default=None, max_length=500)

    @field_validator("balance", mode="before")
    @classmethod
    def validate_balance(cls, value: Any) -> Any:
        if value is None:
            return None
        return _money_before(value)

    @field_validator("description", mode="before")
    @classmethod
    def clean_description(cls, value: object) -> object:
        return _empty_to_none(value)


class EntryPublic(BaseModel):
    id: uuid.UUID
    kind: EntryKind
    account_id: uuid.UUID
    counter_account_id: uuid.UUID | None
    category_id: uuid.UUID | None
    category_name: str | None
    amount: str
    effect: str
    occurred_on: date
    description: str | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EntryPage(BaseModel):
    items: list[EntryPublic]
    next_cursor: str | None


class SummaryPublic(BaseModel):
    as_of: date
    period_from: date
    period_to: date
    total_balance: str
    period_income: str
    period_expense: str
    period_result: str
