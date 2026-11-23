"""Núcleo financeiro.

O saldo de uma conta é calculado somente pela função SQL
``financial_account_position``. Ela soma o saldo inicial e as pernas da view
``financial_entry_effects`` com ``deleted_at`` nulo e ``occurred_on <= data``.

Não existe ordem dentro do mesmo dia: a data é DATE, então todas as pernas
válidas daquela data entram juntas. Um ajuste grava o delta calculado no
momento da operação e esse valor não é reescrito quando outro lançamento da
mesma data, ou de qualquer data, muda depois.

Toda escrita trava as contas afetadas com ``SELECT … FOR UPDATE``, em ordem
crescente de UUID, antes de ler saldo ou alterar saldo inicial, data de
abertura, arquivamento ou lançamentos. Obrigações vinculadas são travadas
depois das contas e das categorias.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select, text, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.time import local_today, utcnow
from app.models.category import Category
from app.models.financial_account import FinancialAccount
from app.models.financial_entry import FinancialEntry
from app.models.user import User
from app.schemas.finance import (
    CATEGORY_GROUPS,
    AccountCreate,
    AccountPublic,
    AccountUpdate,
    AdjustmentCreate,
    AdjustmentUpdate,
    BalancePublic,
    CategoryCreate,
    CategoryPublic,
    CategoryUpdate,
    EntryPage,
    EntryPublic,
    SummaryPublic,
    TransactionCreate,
    TransactionUpdate,
    TransferCreate,
    TransferUpdate,
    ensure_money,
    format_money,
)
from app.services.audit_service import add_audit

DEFAULT_ACCOUNT_NAME = "Dinheiro"
ADJUSTMENT_CODE = "balance_adjustment"
ADJUSTMENT_CATEGORY_NAME = "Ajuste de saldo"
INCOME = "income"
EXPENSE = "expense"
TRANSFER = "transfer"
ADJUSTMENT = "adjustment"
ACCOUNT_ENTITY = "financial_account"
CATEGORY_ENTITY = "category"
ENTRY_ENTITY = "financial_entry"


class FinanceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class IdempotencyConflict(Exception):
    """A chave de idempotência foi gravada por outra transação já confirmada."""


@dataclass(frozen=True)
class AccountPosition:
    balance: Decimal
    income_total: Decimal
    expense_total: Decimal


def money(value: Any, *, positive: bool = False) -> Decimal:
    try:
        return ensure_money(value, positive=positive)
    except ValueError as exc:
        raise FinanceError(422, str(exc)) from None


def provision_user_finance(db: Session, user: User) -> None:
    default_account = db.scalar(
        select(FinancialAccount).where(
            FinancialAccount.user_id == user.id,
            FinancialAccount.is_default.is_(True),
        )
    )
    if default_account is None:
        account = FinancialAccount(
            user_id=user.id,
            name=DEFAULT_ACCOUNT_NAME,
            initial_balance=Decimal("0.00"),
            opened_on=local_today(),
            is_default=True,
        )
        db.add(account)
        db.flush()
        add_audit(
            db,
            user_id=user.id,
            entity_type=ACCOUNT_ENTITY,
            entity_id=account.id,
            operation="create",
            before=None,
            after=_account_snapshot(account),
        )

    internal = db.scalar(
        select(Category).where(
            Category.user_id == user.id,
            Category.code == ADJUSTMENT_CODE,
        )
    )
    if internal is None:
        category = Category(
            user_id=user.id,
            name=ADJUSTMENT_CATEGORY_NAME,
            code=ADJUSTMENT_CODE,
            is_internal=True,
        )
        db.add(category)
        db.flush()
        add_audit(
            db,
            user_id=user.id,
            entity_type=CATEGORY_ENTITY,
            entity_id=category.id,
            operation="create",
            before=None,
            after=_category_snapshot(category),
        )


def list_accounts(db: Session, user: User, *, include_archived: bool) -> list[AccountPublic]:
    statement = select(FinancialAccount).where(FinancialAccount.user_id == user.id)
    if not include_archived:
        statement = statement.where(FinancialAccount.archived_at.is_(None))
    statement = statement.order_by(FinancialAccount.created_at, FinancialAccount.id)
    return [_public_account(db, account) for account in db.scalars(statement)]


def create_account(db: Session, user: User, payload: AccountCreate) -> AccountPublic:
    opened_on = payload.opened_on or local_today()
    _ensure_opening_not_future(opened_on)
    account = FinancialAccount(
        user_id=user.id,
        name=payload.name,
        initial_balance=money(payload.initial_balance),
        opened_on=opened_on,
        is_default=False,
    )
    with _financial_transaction(db):
        db.add(account)
        db.flush()
        add_audit(
            db,
            user_id=user.id,
            entity_type=ACCOUNT_ENTITY,
            entity_id=account.id,
            operation="create",
            before=None,
            after=_account_snapshot(account),
        )
    db.refresh(account)
    return _public_account(db, account)


def get_account(db: Session, user: User, account_id: uuid.UUID) -> AccountPublic:
    return _public_account(db, _owned_account(db, user.id, account_id))


def update_account(
    db: Session,
    user: User,
    account_id: uuid.UUID,
    payload: AccountUpdate,
) -> AccountPublic:
    with _financial_transaction(db):
        account = _lock_accounts(db, user.id, [account_id])[account_id]
        before = _account_snapshot(account)
        if "name" in payload.model_fields_set:
            if not payload.name:
                raise FinanceError(422, "Informe o nome da conta.")
            account.name = payload.name
        if "initial_balance" in payload.model_fields_set:
            if payload.initial_balance is None:
                raise FinanceError(422, "Informe o saldo inicial.")
            account.initial_balance = money(payload.initial_balance)
        if "opened_on" in payload.model_fields_set:
            if payload.opened_on is None:
                raise FinanceError(422, "Informe a data de início do controle.")
            _ensure_opening_revision(db, account, payload.opened_on)
            account.opened_on = payload.opened_on
        account.updated_at = utcnow()
        after = _account_snapshot(account)
        if before == after:
            raise FinanceError(422, "Nenhuma alteração informada.")
        add_audit(
            db,
            user_id=user.id,
            entity_type=ACCOUNT_ENTITY,
            entity_id=account.id,
            operation="update",
            before=before,
            after=after,
        )
    db.refresh(account)
    return _public_account(db, account)


def archive_account(db: Session, user: User, account_id: uuid.UUID) -> AccountPublic:
    with _financial_transaction(db):
        account = _lock_accounts(db, user.id, [account_id])[account_id]
        if account.archived_at is not None:
            raise FinanceError(409, "A conta já está arquivada.")
        before = _account_snapshot(account)
        account.archived_at = utcnow()
        account.updated_at = account.archived_at
        add_audit(
            db,
            user_id=user.id,
            entity_type=ACCOUNT_ENTITY,
            entity_id=account.id,
            operation="archive",
            before=before,
            after=_account_snapshot(account),
        )
    db.refresh(account)
    return _public_account(db, account)


def reactivate_account(db: Session, user: User, account_id: uuid.UUID) -> AccountPublic:
    with _financial_transaction(db):
        account = _lock_accounts(db, user.id, [account_id])[account_id]
        if account.archived_at is None:
            raise FinanceError(409, "A conta já está ativa.")
        before = _account_snapshot(account)
        account.archived_at = None
        account.updated_at = utcnow()
        add_audit(
            db,
            user_id=user.id,
            entity_type=ACCOUNT_ENTITY,
            entity_id=account.id,
            operation="reactivate",
            before=before,
            after=_account_snapshot(account),
        )
    db.refresh(account)
    return _public_account(db, account)


def get_account_balance(
    db: Session,
    user: User,
    account_id: uuid.UUID,
    as_of: date | None,
) -> BalancePublic:
    account = _owned_account(db, user.id, account_id)
    effective = as_of or local_today()
    position = _position_for_account(db, account, effective)
    return BalancePublic(
        account_id=account.id,
        as_of=effective,
        balance=format_money(position.balance),
        income_total=format_money(position.income_total),
        expense_total=format_money(position.expense_total),
    )


def get_summary(
    db: Session,
    user: User,
    *,
    occurred_from: date | None,
    occurred_to: date | None,
) -> SummaryPublic:
    """Agrega a posição atual e o resultado do período sem recalcular regras.

    O saldo total soma ``financial_account_position`` de todas as contas do
    usuário, inclusive arquivadas. Receitas e despesas do período usam os
    mesmos filtros da função existente: lançamentos não excluídos, apenas
    ``income`` e ``expense``. Transferências e ajustes ficam de fora.
    """

    today = local_today()
    start = occurred_from or date(today.year, today.month, 1)
    end = occurred_to or today
    if start > end:
        raise FinanceError(422, "A data inicial não pode ser posterior à data final.")

    total = Decimal("0.00")
    accounts = db.scalars(select(FinancialAccount).where(FinancialAccount.user_id == user.id))
    for account in accounts:
        total += _position_for_account(db, account, today).balance

    income = _period_kind_total(db, user.id, INCOME, start, end)
    expense = _period_kind_total(db, user.id, EXPENSE, start, end)
    return SummaryPublic(
        as_of=today,
        period_from=start,
        period_to=end,
        total_balance=format_money(total),
        period_income=format_money(income),
        period_expense=format_money(expense),
        period_result=format_money(income - expense),
    )


def _period_kind_total(
    db: Session,
    user_id: uuid.UUID,
    kind: str,
    start: date,
    end: date,
) -> Decimal:
    raw = db.execute(
        text(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM financial_entries
            WHERE user_id = :user_id
              AND deleted_at IS NULL
              AND kind = :kind
              AND occurred_on >= :start
              AND occurred_on <= :end
            """
        ),
        {"user_id": user_id, "kind": kind, "start": start, "end": end},
    ).scalar_one()
    return Decimal(raw)


def list_categories(db: Session, user: User, *, include_archived: bool) -> list[CategoryPublic]:
    statement = select(Category).where(Category.user_id == user.id)
    if not include_archived:
        statement = statement.where(Category.archived_at.is_(None))
    statement = statement.order_by(Category.is_internal, Category.name, Category.id)
    return [_public_category(category) for category in db.scalars(statement)]


def create_category(db: Session, user: User, payload: CategoryCreate) -> CategoryPublic:
    _ensure_group(payload.group_code)
    category = Category(
        user_id=user.id,
        name=payload.name,
        group_code=payload.group_code,
        is_internal=False,
    )
    with _financial_transaction(db):
        db.add(category)
        db.flush()
        add_audit(
            db,
            user_id=user.id,
            entity_type=CATEGORY_ENTITY,
            entity_id=category.id,
            operation="create",
            before=None,
            after=_category_snapshot(category),
        )
    db.refresh(category)
    return _public_category(category)


def update_category(
    db: Session,
    user: User,
    category_id: uuid.UUID,
    payload: CategoryUpdate,
) -> CategoryPublic:
    with _financial_transaction(db):
        category = _lock_categories(db, user.id, [category_id])[category_id]
        before = _category_snapshot(category)
        if "name" in payload.model_fields_set:
            if not payload.name:
                raise FinanceError(422, "Informe o nome da categoria.")
            category.name = payload.name
        if "group_code" in payload.model_fields_set:
            _ensure_group(payload.group_code)
            if category.is_internal and payload.group_code is not None:
                raise FinanceError(422, "A categoria interna não pode receber grupo.")
            category.group_code = payload.group_code
        category.updated_at = utcnow()
        after = _category_snapshot(category)
        if before == after:
            raise FinanceError(422, "Nenhuma alteração informada.")
        add_audit(
            db,
            user_id=user.id,
            entity_type=CATEGORY_ENTITY,
            entity_id=category.id,
            operation="update",
            before=before,
            after=after,
        )
    db.refresh(category)
    return _public_category(category)


def archive_category(db: Session, user: User, category_id: uuid.UUID) -> CategoryPublic:
    with _financial_transaction(db):
        category = _lock_categories(db, user.id, [category_id])[category_id]
        if category.is_internal:
            raise FinanceError(422, "A categoria interna não pode ser arquivada.")
        if category.archived_at is not None:
            raise FinanceError(409, "A categoria já está arquivada.")
        before = _category_snapshot(category)
        category.archived_at = utcnow()
        category.updated_at = category.archived_at
        add_audit(
            db,
            user_id=user.id,
            entity_type=CATEGORY_ENTITY,
            entity_id=category.id,
            operation="archive",
            before=before,
            after=_category_snapshot(category),
        )
    db.refresh(category)
    return _public_category(category)


def reactivate_category(db: Session, user: User, category_id: uuid.UUID) -> CategoryPublic:
    with _financial_transaction(db):
        category = _lock_categories(db, user.id, [category_id])[category_id]
        if category.archived_at is None:
            raise FinanceError(409, "A categoria já está ativa.")
        before = _category_snapshot(category)
        category.archived_at = None
        category.updated_at = utcnow()
        add_audit(
            db,
            user_id=user.id,
            entity_type=CATEGORY_ENTITY,
            entity_id=category.id,
            operation="reactivate",
            before=before,
            after=_category_snapshot(category),
        )
    db.refresh(category)
    return _public_category(category)


def list_transactions(
    db: Session,
    user: User,
    *,
    account_id: uuid.UUID | None,
    category_id: uuid.UUID | None,
    kind: str | None,
    occurred_from: date | None,
    occurred_to: date | None,
    description: str | None,
    include_deleted: bool,
    order: str,
    limit: int,
    cursor: str | None,
) -> EntryPage:
    if occurred_from is not None and occurred_to is not None and occurred_from > occurred_to:
        raise FinanceError(422, "A data inicial não pode ser posterior à data final.")
    if account_id is not None:
        _owned_account(db, user.id, account_id)
    if category_id is not None:
        _owned_category(db, user.id, category_id)

    statement = select(FinancialEntry).where(FinancialEntry.user_id == user.id)
    if not include_deleted:
        statement = statement.where(FinancialEntry.deleted_at.is_(None))
    if account_id is not None:
        statement = statement.where(
            or_(
                FinancialEntry.account_id == account_id,
                FinancialEntry.counter_account_id == account_id,
            )
        )
    if category_id is not None:
        statement = statement.where(FinancialEntry.category_id == category_id)
    if kind is not None:
        statement = statement.where(FinancialEntry.kind == kind)
    if occurred_from is not None:
        statement = statement.where(FinancialEntry.occurred_on >= occurred_from)
    if occurred_to is not None:
        statement = statement.where(FinancialEntry.occurred_on <= occurred_to)
    if description is not None and description.strip():
        statement = statement.where(
            FinancialEntry.description.ilike(_like_pattern(description.strip()), escape="\\")
        )
    if cursor is not None:
        cursor_date, cursor_id = _decode_cursor(cursor)
        row = tuple_(FinancialEntry.occurred_on, FinancialEntry.id)
        marker = (cursor_date, cursor_id)
        if order == "asc":
            statement = statement.where(row > marker)
        else:
            statement = statement.where(row < marker)
    if order == "asc":
        statement = statement.order_by(FinancialEntry.occurred_on.asc(), FinancialEntry.id.asc())
    else:
        statement = statement.order_by(FinancialEntry.occurred_on.desc(), FinancialEntry.id.desc())

    rows = list(db.scalars(statement.limit(limit + 1)))
    has_more = len(rows) > limit
    visible = rows[:limit]
    names = _category_names(db, visible)
    items = [
        _public_entry(entry, names.get(entry.category_id) if entry.category_id else None, account_id)
        for entry in visible
    ]
    next_cursor = None
    if has_more and visible:
        last = visible[-1]
        next_cursor = _encode_cursor(last.occurred_on, last.id)
    return EntryPage(items=items, next_cursor=next_cursor)


def get_transaction(db: Session, user: User, entry_id: uuid.UUID) -> EntryPublic:
    entry = _owned_entry(db, user.id, entry_id)
    return _public_entry(entry, _category_name(db, entry.category_id), None)


def create_transaction(db: Session, user: User, payload: TransactionCreate) -> EntryPublic:
    amount = money(payload.amount, positive=True)
    with _financial_transaction(db):
        account = _lock_accounts(db, user.id, [payload.account_id])[payload.account_id]
        category = _lock_categories(db, user.id, [payload.category_id])[payload.category_id]
        entry = _insert_expense(
            db,
            user,
            account=account,
            category=category,
            amount=amount,
            occurred_on=payload.occurred_on,
            description=payload.description,
            kind=payload.kind,
        )
    db.refresh(entry)
    return _public_entry(entry, category.name, None)


def _insert_expense(
    db: Session,
    user: User,
    *,
    account: FinancialAccount,
    category: Category,
    amount: Decimal,
    occurred_on: date,
    description: str | None,
    kind: str,
    entry_id: uuid.UUID | None = None,
) -> FinancialEntry:
    _ensure_accepts_new_movement(account)
    _ensure_category_for_ordinary(category, new_entry=True)
    _ensure_not_future(occurred_on)
    _ensure_on_or_after_opening(account, occurred_on)
    entry = FinancialEntry(
        id=entry_id or uuid.uuid4(),
        user_id=user.id,
        kind=kind,
        account_id=account.id,
        category_id=category.id,
        amount=amount,
        occurred_on=occurred_on,
        description=description,
    )
    db.add(entry)
    db.flush()
    add_audit(
        db,
        user_id=user.id,
        entity_type=ENTRY_ENTITY,
        entity_id=entry.id,
        operation="create",
        before=None,
        after=_entry_snapshot(entry),
    )
    return entry


def update_transaction(
    db: Session,
    user: User,
    entry_id: uuid.UUID,
    payload: TransactionUpdate,
) -> EntryPublic:
    with _financial_transaction(db):
        entry = _owned_entry(db, user.id, entry_id)
        _ensure_ordinary(entry)
        if entry.deleted_at is not None:
            raise FinanceError(409, "Restaure o lançamento antes de editá-lo.")
        account_ids = {entry.account_id}
        if "account_id" in payload.model_fields_set:
            if payload.account_id is None:
                raise FinanceError(422, "Informe a conta.")
            account_ids.add(payload.account_id)
        category_ids = {entry.category_id} if entry.category_id else set()
        if "category_id" in payload.model_fields_set:
            if payload.category_id is None:
                raise FinanceError(422, "Informe a categoria.")
            category_ids.add(payload.category_id)
        accounts = _lock_accounts(db, user.id, account_ids)
        _refresh_locked_entry(db, entry, accounts)
        _ensure_ordinary(entry)
        if entry.deleted_at is not None:
            raise FinanceError(409, "Restaure o lançamento antes de editá-lo.")
        before = _entry_snapshot(entry)
        categories = _lock_categories(db, user.id, category_ids)
        from app.services.payable_service import lock_linked_obligations, sync_linked_allocation

        linked = lock_linked_obligations(db, user, entry)
        previous_amount = entry.amount
        if "account_id" in payload.model_fields_set and payload.account_id is not None:
            entry.account_id = payload.account_id
        if "category_id" in payload.model_fields_set and payload.category_id is not None:
            entry.category_id = payload.category_id
        if "amount" in payload.model_fields_set:
            if payload.amount is None:
                raise FinanceError(422, "Informe o valor.")
            entry.amount = money(payload.amount, positive=True)
        if "occurred_on" in payload.model_fields_set:
            if payload.occurred_on is None:
                raise FinanceError(422, "Informe a data.")
            entry.occurred_on = payload.occurred_on
        if "description" in payload.model_fields_set:
            entry.description = payload.description
        account = accounts[entry.account_id]
        category = categories[entry.category_id]
        _ensure_category_for_ordinary(category, new_entry=False)
        _ensure_not_future(entry.occurred_on)
        _ensure_on_or_after_opening(account, entry.occurred_on)
        entry.updated_at = utcnow()
        after = _entry_snapshot(entry)
        if before == after:
            raise FinanceError(422, "Nenhuma alteração informada.")
        sync_linked_allocation(db, user, entry, linked, previous_amount)
        add_audit(
            db,
            user_id=user.id,
            entity_type=ENTRY_ENTITY,
            entity_id=entry.id,
            operation="update",
            before=before,
            after=after,
        )
        category_name = category.name
    db.refresh(entry)
    return _public_entry(entry, category_name, None)


def delete_transaction(db: Session, user: User, entry_id: uuid.UUID) -> EntryPublic:
    with _financial_transaction(db):
        entry = _owned_entry(db, user.id, entry_id)
        _ensure_ordinary(entry)
        _mark_deleted(db, user, entry)
        category_name = _category_name(db, entry.category_id)
    db.refresh(entry)
    return _public_entry(entry, category_name, None)


def restore_transaction(db: Session, user: User, entry_id: uuid.UUID) -> EntryPublic:
    with _financial_transaction(db):
        entry = _owned_entry(db, user.id, entry_id)
        _ensure_ordinary(entry)
        category = _restore_entry(db, user, entry)
        category_name = category.name if category is not None else None
    db.refresh(entry)
    return _public_entry(entry, category_name, None)


def create_transfer(db: Session, user: User, payload: TransferCreate) -> EntryPublic:
    amount = money(payload.amount, positive=True)
    if payload.from_account_id == payload.to_account_id:
        raise FinanceError(422, "A conta de origem e a de destino devem ser diferentes.")
    with _financial_transaction(db):
        accounts = _lock_accounts(db, user.id, [payload.from_account_id, payload.to_account_id])
        origin = accounts[payload.from_account_id]
        destination = accounts[payload.to_account_id]
        _ensure_accepts_new_movement(origin)
        _ensure_accepts_new_movement(destination)
        _ensure_not_future(payload.occurred_on)
        _ensure_on_or_after_opening(origin, payload.occurred_on)
        _ensure_on_or_after_opening(destination, payload.occurred_on)
        entry = FinancialEntry(
            user_id=user.id,
            kind=TRANSFER,
            account_id=origin.id,
            counter_account_id=destination.id,
            amount=amount,
            occurred_on=payload.occurred_on,
            description=payload.description,
        )
        db.add(entry)
        db.flush()
        add_audit(
            db,
            user_id=user.id,
            entity_type=ENTRY_ENTITY,
            entity_id=entry.id,
            operation="create",
            before=None,
            after=_entry_snapshot(entry),
        )
    db.refresh(entry)
    return _public_entry(entry, None, None)


def update_transfer(
    db: Session,
    user: User,
    entry_id: uuid.UUID,
    payload: TransferUpdate,
) -> EntryPublic:
    with _financial_transaction(db):
        entry = _transfer_entry(db, user.id, entry_id)
        origin_id = entry.account_id
        destination_id = entry.counter_account_id
        if "from_account_id" in payload.model_fields_set:
            if payload.from_account_id is None:
                raise FinanceError(422, "Informe a conta de origem.")
            origin_id = payload.from_account_id
        if "to_account_id" in payload.model_fields_set:
            if payload.to_account_id is None:
                raise FinanceError(422, "Informe a conta de destino.")
            destination_id = payload.to_account_id
        if destination_id is None or origin_id == destination_id:
            raise FinanceError(422, "A conta de origem e a de destino devem ser diferentes.")
        accounts = _lock_accounts(
            db,
            user.id,
            [entry.account_id, entry.counter_account_id, origin_id, destination_id],
        )
        _refresh_locked_entry(db, entry, accounts)
        if entry.deleted_at is not None:
            raise FinanceError(409, "Restaure a transferência antes de editá-la.")
        before = _entry_snapshot(entry)
        if "amount" in payload.model_fields_set:
            if payload.amount is None:
                raise FinanceError(422, "Informe o valor.")
            entry.amount = money(payload.amount, positive=True)
        if "occurred_on" in payload.model_fields_set:
            if payload.occurred_on is None:
                raise FinanceError(422, "Informe a data.")
            entry.occurred_on = payload.occurred_on
        if "description" in payload.model_fields_set:
            entry.description = payload.description
        entry.account_id = origin_id
        entry.counter_account_id = destination_id
        entry.updated_at = utcnow()
        _ensure_not_future(entry.occurred_on)
        _ensure_on_or_after_opening(accounts[origin_id], entry.occurred_on)
        _ensure_on_or_after_opening(accounts[destination_id], entry.occurred_on)
        after = _entry_snapshot(entry)
        if before == after:
            raise FinanceError(422, "Nenhuma alteração informada.")
        add_audit(
            db,
            user_id=user.id,
            entity_type=ENTRY_ENTITY,
            entity_id=entry.id,
            operation="update",
            before=before,
            after=after,
        )
    db.refresh(entry)
    return _public_entry(entry, None, None)


def delete_transfer(db: Session, user: User, entry_id: uuid.UUID) -> EntryPublic:
    with _financial_transaction(db):
        entry = _transfer_entry(db, user.id, entry_id)
        _mark_deleted(db, user, entry)
    db.refresh(entry)
    return _public_entry(entry, None, None)


def restore_transfer(db: Session, user: User, entry_id: uuid.UUID) -> EntryPublic:
    with _financial_transaction(db):
        entry = _transfer_entry(db, user.id, entry_id)
        _restore_entry(db, user, entry)
    db.refresh(entry)
    return _public_entry(entry, None, None)


def create_adjustment(
    db: Session,
    user: User,
    account_id: uuid.UUID,
    payload: AdjustmentCreate,
) -> EntryPublic:
    """Grava o delta entre o saldo desejado e o saldo já existente na data.

    O saldo da data inclui o saldo inicial e todas as pernas válidas com
    ``occurred_on`` menor ou igual à data do ajuste. Lançamentos do mesmo dia
    já gravados entram juntos; não há hora para ordená-los. O delta resultante
    permanece armazenado mesmo que esses lançamentos sejam editados depois.
    """

    target = money(payload.balance)
    with _financial_transaction(db):
        account = _lock_accounts(db, user.id, [account_id])[account_id]
        _ensure_accepts_new_movement(account)
        _ensure_not_future(payload.occurred_on)
        _ensure_on_or_after_opening(account, payload.occurred_on)
        category = _lock_adjustment_category(db, user.id)
        delta = _adjustment_delta(db, account, payload.occurred_on, target, excluded=None)
        entry = FinancialEntry(
            user_id=user.id,
            kind=ADJUSTMENT,
            account_id=account.id,
            category_id=category.id,
            amount=delta,
            occurred_on=payload.occurred_on,
            description=payload.description,
        )
        db.add(entry)
        db.flush()
        add_audit(
            db,
            user_id=user.id,
            entity_type=ENTRY_ENTITY,
            entity_id=entry.id,
            operation="create",
            before=None,
            after=_entry_snapshot(entry),
        )
    db.refresh(entry)
    return _public_entry(entry, category.name, account.id)


def update_adjustment(
    db: Session,
    user: User,
    account_id: uuid.UUID,
    adjustment_id: uuid.UUID,
    payload: AdjustmentUpdate,
) -> EntryPublic:
    """Recalcula o delta sem incluir a própria linha e mantém o mesmo id.

    A nova diferença também fica congelada. Alterações posteriores em outros
    lançamentos não modificam este valor.
    """

    with _financial_transaction(db):
        account = _lock_accounts(db, user.id, [account_id])[account_id]
        entry = _adjustment_entry(db, user.id, account_id, adjustment_id)
        if entry.deleted_at is not None:
            raise FinanceError(409, "Restaure o ajuste antes de editá-lo.")
        before = _entry_snapshot(entry)
        occurred_on = entry.occurred_on
        if "occurred_on" in payload.model_fields_set:
            if payload.occurred_on is None:
                raise FinanceError(422, "Informe a data.")
            occurred_on = payload.occurred_on
        _ensure_not_future(occurred_on)
        _ensure_on_or_after_opening(account, occurred_on)
        category = _lock_adjustment_category(db, user.id)
        if "balance" in payload.model_fields_set:
            if payload.balance is None:
                raise FinanceError(422, "Informe o saldo.")
            entry.amount = _adjustment_delta(
                db,
                account,
                occurred_on,
                money(payload.balance),
                excluded=entry,
            )
        entry.occurred_on = occurred_on
        if "description" in payload.model_fields_set:
            entry.description = payload.description
        entry.category_id = category.id
        entry.updated_at = utcnow()
        after = _entry_snapshot(entry)
        if before == after:
            raise FinanceError(422, "Nenhuma alteração informada.")
        add_audit(
            db,
            user_id=user.id,
            entity_type=ENTRY_ENTITY,
            entity_id=entry.id,
            operation="update",
            before=before,
            after=after,
        )
    db.refresh(entry)
    return _public_entry(entry, ADJUSTMENT_CATEGORY_NAME, account.id)


def delete_adjustment(
    db: Session,
    user: User,
    account_id: uuid.UUID,
    adjustment_id: uuid.UUID,
) -> EntryPublic:
    with _financial_transaction(db):
        _lock_accounts(db, user.id, [account_id])
        entry = _adjustment_entry(db, user.id, account_id, adjustment_id)
        _mark_deleted(db, user, entry)
    db.refresh(entry)
    return _public_entry(entry, ADJUSTMENT_CATEGORY_NAME, account_id)


def restore_adjustment(
    db: Session,
    user: User,
    account_id: uuid.UUID,
    adjustment_id: uuid.UUID,
) -> EntryPublic:
    with _financial_transaction(db):
        _lock_accounts(db, user.id, [account_id])
        entry = _adjustment_entry(db, user.id, account_id, adjustment_id)
        _restore_entry(db, user, entry)
    db.refresh(entry)
    return _public_entry(entry, ADJUSTMENT_CATEGORY_NAME, account_id)


@contextmanager
def _financial_transaction(db: Session) -> Iterator[None]:
    try:
        yield
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _raise_integrity(exc)
    except Exception:
        db.rollback()
        raise


def _raise_integrity(exc: IntegrityError) -> None:
    diagnostic = getattr(getattr(exc, "orig", None), "diag", None)
    name = getattr(diagnostic, "constraint_name", "") or ""
    marker = f"{name} {exc}"
    if "uq_payable_idempotency_user_key" in marker:
        raise IdempotencyConflict() from None
    if "uq_payable_settlements_one_active" in marker:
        raise FinanceError(409, "A obrigação já possui outra quitação válida.") from None
    if "ck_payable_allocation_balance" in marker or "payable allocation" in marker:
        raise FinanceError(409, "As parcelas do pagamento não fecham com o valor da despesa.") from None
    if "lower_name" in name:
        raise FinanceError(409, "Já existe uma categoria com esse nome.") from None
    if "one_default" in name:
        raise FinanceError(409, "O usuário já possui conta padrão.") from None
    raise FinanceError(409, "Conflito ao gravar os dados financeiros.") from None


def _lock_accounts(
    db: Session,
    user_id: uuid.UUID,
    account_ids: Iterable[uuid.UUID | None],
) -> dict[uuid.UUID, FinancialAccount]:
    locked: dict[uuid.UUID, FinancialAccount] = {}
    for account_id in sorted({account_id for account_id in account_ids if account_id is not None}):
        account = db.scalar(
            select(FinancialAccount)
            .where(
                FinancialAccount.id == account_id,
                FinancialAccount.user_id == user_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if account is None:
            raise FinanceError(404, "Conta financeira não encontrada.")
        locked[account_id] = account
    return locked


def _lock_categories(
    db: Session,
    user_id: uuid.UUID,
    category_ids: Iterable[uuid.UUID | None],
) -> dict[uuid.UUID, Category]:
    locked: dict[uuid.UUID, Category] = {}
    for category_id in sorted({category_id for category_id in category_ids if category_id is not None}):
        category = db.scalar(
            select(Category)
            .where(Category.id == category_id, Category.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if category is None:
            raise FinanceError(404, "Categoria não encontrada.")
        locked[category_id] = category
    return locked


def _owned_account(db: Session, user_id: uuid.UUID, account_id: uuid.UUID) -> FinancialAccount:
    account = db.scalar(
        select(FinancialAccount).where(
            FinancialAccount.id == account_id,
            FinancialAccount.user_id == user_id,
        )
    )
    if account is None:
        raise FinanceError(404, "Conta financeira não encontrada.")
    return account


def _owned_category(db: Session, user_id: uuid.UUID, category_id: uuid.UUID) -> Category:
    category = db.scalar(
        select(Category).where(Category.id == category_id, Category.user_id == user_id)
    )
    if category is None:
        raise FinanceError(404, "Categoria não encontrada.")
    return category


def _owned_entry(db: Session, user_id: uuid.UUID, entry_id: uuid.UUID) -> FinancialEntry:
    entry = db.scalar(
        select(FinancialEntry).where(
            FinancialEntry.id == entry_id,
            FinancialEntry.user_id == user_id,
        )
    )
    if entry is None:
        raise FinanceError(404, "Lançamento não encontrado.")
    return entry


def _transfer_entry(db: Session, user_id: uuid.UUID, entry_id: uuid.UUID) -> FinancialEntry:
    entry = _owned_entry(db, user_id, entry_id)
    if entry.kind != TRANSFER:
        raise FinanceError(404, "Transferência não encontrada.")
    return entry


def _adjustment_entry(
    db: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    entry_id: uuid.UUID,
) -> FinancialEntry:
    entry = _owned_entry(db, user_id, entry_id)
    if entry.kind != ADJUSTMENT or entry.account_id != account_id:
        raise FinanceError(404, "Ajuste não encontrado.")
    return entry


def _lock_adjustment_category(db: Session, user_id: uuid.UUID) -> Category:
    category = db.scalar(
        select(Category).where(Category.user_id == user_id, Category.code == ADJUSTMENT_CODE)
    )
    if category is None:
        raise FinanceError(500, "Categoria interna de ajuste não encontrada.")
    locked = _lock_categories(db, user_id, [category.id])[category.id]
    if not locked.is_internal or locked.archived_at is not None:
        raise FinanceError(422, "A categoria interna de ajuste não está disponível.")
    return locked


def _position_for_account(db: Session, account: FinancialAccount, as_of: date) -> AccountPosition:
    if as_of < account.opened_on:
        raise FinanceError(422, "A data é anterior ao início do controle da conta.")
    row = db.execute(
        text(
            "SELECT balance, income_total, expense_total "
            "FROM financial_account_position(:account_id, :as_of)"
        ),
        {"account_id": account.id, "as_of": as_of},
    ).one_or_none()
    if row is None:
        raise FinanceError(422, "A data é anterior ao início do controle da conta.")
    return AccountPosition(
        balance=Decimal(row.balance),
        income_total=Decimal(row.income_total),
        expense_total=Decimal(row.expense_total),
    )


def _balance_without(
    db: Session,
    account: FinancialAccount,
    as_of: date,
    entry: FinancialEntry | None,
) -> Decimal:
    balance = _position_for_account(db, account, as_of).balance
    if entry is not None and entry.deleted_at is None and entry.occurred_on <= as_of:
        if entry.account_id == account.id or entry.counter_account_id == account.id:
            balance -= entry_effect(entry, account.id)
    return balance


def _adjustment_delta(
    db: Session,
    account: FinancialAccount,
    occurred_on: date,
    target: Decimal,
    excluded: FinancialEntry | None,
) -> Decimal:
    current = money(_balance_without(db, account, occurred_on, excluded))
    return _require_delta(money(target - current))


def _require_delta(delta: Decimal) -> Decimal:
    if delta == 0:
        raise FinanceError(422, "O saldo informado já é o saldo da conta nessa data.")
    return delta


def entry_effect(entry: FinancialEntry, perspective: uuid.UUID | None) -> Decimal:
    if entry.kind == TRANSFER:
        if perspective is not None and perspective == entry.counter_account_id:
            return entry.amount
        return -entry.amount
    if entry.kind == EXPENSE:
        return -entry.amount
    return entry.amount


def _ensure_not_future(occurred_on: date) -> None:
    if occurred_on > local_today():
        raise FinanceError(422, "Não é permitido lançamento em data futura.")


def _ensure_opening_not_future(opened_on: date) -> None:
    if opened_on > local_today():
        raise FinanceError(422, "A data de início do controle não pode ser futura.")


def _ensure_on_or_after_opening(account: FinancialAccount, occurred_on: date) -> None:
    if occurred_on < account.opened_on:
        raise FinanceError(422, "A data é anterior ao início do controle da conta.")


def _ensure_opening_revision(db: Session, account: FinancialAccount, opened_on: date) -> None:
    _ensure_opening_not_future(opened_on)
    conflict = db.scalar(
        select(FinancialEntry.id).where(
            FinancialEntry.user_id == account.user_id,
            FinancialEntry.deleted_at.is_(None),
            FinancialEntry.occurred_on < opened_on,
            or_(
                FinancialEntry.account_id == account.id,
                FinancialEntry.counter_account_id == account.id,
            ),
        )
    )
    if conflict is not None:
        raise FinanceError(
            422,
            "Existe lançamento anterior à nova data de início do controle.",
        )


def _ensure_accepts_new_movement(account: FinancialAccount) -> None:
    if account.archived_at is not None:
        raise FinanceError(422, "A conta arquivada não aceita novos lançamentos.")


def _ensure_category_for_ordinary(category: Category, *, new_entry: bool) -> None:
    if category.is_internal:
        raise FinanceError(422, "A categoria interna não pode ser usada em receitas ou despesas.")
    if new_entry and category.archived_at is not None:
        raise FinanceError(422, "A categoria arquivada não aceita novos lançamentos.")


def _ensure_group(group_code: str | None) -> None:
    if group_code is not None and group_code not in CATEGORY_GROUPS:
        raise FinanceError(422, "Grupo de categoria indisponível.")


def _ensure_ordinary(entry: FinancialEntry) -> None:
    if entry.kind == TRANSFER:
        raise FinanceError(409, "Transferências são alteradas em /transfers/{id}.")
    if entry.kind == ADJUSTMENT:
        raise FinanceError(
            409,
            "Ajustes de saldo são alterados em /accounts/{id}/adjustments/{adjustment_id}.",
        )


def _refresh_locked_entry(
    db: Session,
    entry: FinancialEntry,
    accounts: dict[uuid.UUID, FinancialAccount],
) -> None:
    db.refresh(entry)
    needed = {entry.account_id}
    if entry.counter_account_id is not None:
        needed.add(entry.counter_account_id)
    if not needed <= set(accounts):
        raise FinanceError(409, "O lançamento foi alterado por outra operação. Repita a operação.")


def _mark_deleted(db: Session, user: User, entry: FinancialEntry) -> None:
    accounts = _lock_accounts(db, user.id, [entry.account_id, entry.counter_account_id])
    _refresh_locked_entry(db, entry, accounts)
    if entry.deleted_at is not None:
        raise FinanceError(409, "O lançamento já está excluído.")
    from app.services.payable_service import lock_linked_obligations, release_linked_settlements

    linked = lock_linked_obligations(db, user, entry)
    before = _entry_snapshot(entry)
    entry.deleted_at = utcnow()
    entry.updated_at = entry.deleted_at
    add_audit(
        db,
        user_id=user.id,
        entity_type=ENTRY_ENTITY,
        entity_id=entry.id,
        operation="delete",
        before=before,
        after=_entry_snapshot(entry),
    )
    release_linked_settlements(db, user, entry, linked)


def _restore_entry(db: Session, user: User, entry: FinancialEntry) -> Category | None:
    accounts = _lock_accounts(db, user.id, [entry.account_id, entry.counter_account_id])
    _refresh_locked_entry(db, entry, accounts)
    if entry.deleted_at is None:
        raise FinanceError(409, "O lançamento não está excluído.")
    category = None
    if entry.category_id is not None:
        category = _lock_categories(db, user.id, [entry.category_id])[entry.category_id]
    before = _entry_snapshot(entry)
    _ensure_not_future(entry.occurred_on)
    _ensure_on_or_after_opening(accounts[entry.account_id], entry.occurred_on)
    if entry.counter_account_id is not None:
        _ensure_on_or_after_opening(accounts[entry.counter_account_id], entry.occurred_on)
    if entry.kind in {INCOME, EXPENSE}:
        if category is None or category.is_internal:
            raise FinanceError(422, "A categoria não pode ser usada neste lançamento.")
    if entry.kind == ADJUSTMENT and (category is None or not category.is_internal):
        raise FinanceError(422, "A categoria interna de ajuste não está disponível.")
    from app.services.payable_service import claim_linked_restore, finish_linked_restore

    linked = claim_linked_restore(db, user, entry)
    entry.deleted_at = None
    entry.updated_at = utcnow()
    add_audit(
        db,
        user_id=user.id,
        entity_type=ENTRY_ENTITY,
        entity_id=entry.id,
        operation="restore",
        before=before,
        after=_entry_snapshot(entry),
    )
    finish_linked_restore(db, user, linked)
    return category


def _public_account(db: Session, account: FinancialAccount) -> AccountPublic:
    position = _position_for_account(db, account, local_today())
    return AccountPublic(
        id=account.id,
        name=account.name,
        initial_balance=format_money(account.initial_balance),
        opened_on=account.opened_on,
        is_default=account.is_default,
        archived_at=account.archived_at,
        balance=format_money(position.balance),
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def _public_category(category: Category) -> CategoryPublic:
    return CategoryPublic(
        id=category.id,
        name=category.name,
        group_code=category.group_code,
        code=category.code,
        is_internal=category.is_internal,
        archived_at=category.archived_at,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )


def _public_entry(
    entry: FinancialEntry,
    category_name: str | None,
    perspective: uuid.UUID | None,
) -> EntryPublic:
    return EntryPublic(
        id=entry.id,
        kind=entry.kind,  # type: ignore[arg-type]
        account_id=entry.account_id,
        counter_account_id=entry.counter_account_id,
        category_id=entry.category_id,
        category_name=category_name,
        amount=format_money(entry.amount),
        effect=format_money(entry_effect(entry, perspective)),
        occurred_on=entry.occurred_on,
        description=entry.description,
        deleted_at=entry.deleted_at,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _category_name(db: Session, category_id: uuid.UUID | None) -> str | None:
    if category_id is None:
        return None
    return db.scalar(select(Category.name).where(Category.id == category_id))


def _category_names(db: Session, entries: list[FinancialEntry]) -> dict[uuid.UUID, str]:
    identifiers = {entry.category_id for entry in entries if entry.category_id is not None}
    if not identifiers:
        return {}
    rows = db.execute(select(Category.id, Category.name).where(Category.id.in_(identifiers))).all()
    return {row.id: row.name for row in rows}


def _account_snapshot(account: FinancialAccount) -> dict[str, Any]:
    return {
        "id": str(account.id),
        "name": account.name,
        "initial_balance": format_money(account.initial_balance),
        "opened_on": account.opened_on.isoformat(),
        "is_default": account.is_default,
        "archived_at": account.archived_at.isoformat() if account.archived_at else None,
    }


def _category_snapshot(category: Category) -> dict[str, Any]:
    return {
        "id": str(category.id),
        "name": category.name,
        "group_code": category.group_code,
        "code": category.code,
        "is_internal": category.is_internal,
        "archived_at": category.archived_at.isoformat() if category.archived_at else None,
    }


def _entry_snapshot(entry: FinancialEntry) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "kind": entry.kind,
        "account_id": str(entry.account_id),
        "counter_account_id": str(entry.counter_account_id) if entry.counter_account_id else None,
        "category_id": str(entry.category_id) if entry.category_id else None,
        "amount": format_money(entry.amount),
        "occurred_on": entry.occurred_on.isoformat(),
        "description": entry.description,
        "deleted_at": entry.deleted_at.isoformat() if entry.deleted_at else None,
    }


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _encode_cursor(occurred_on: date, entry_id: uuid.UUID) -> str:
    payload = f"{occurred_on.isoformat()}|{entry_id}"
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[date, uuid.UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        day, entry_id = raw.split("|", 1)
        return date.fromisoformat(day), uuid.UUID(entry_id)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise FinanceError(422, "Cursor inválido.") from None
