"""Contas a pagar.

A obrigação não é uma despesa. O saldo só muda quando o pagamento grava uma
despesa pelo mesmo caminho de ``_insert_expense``.

Ordem global de locks, com ids crescentes em cada nível:
contas, categorias, chave de idempotência, obrigações e só então a escrita.
Quem não usa um nível simplesmente o pula.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import exists, func, select, tuple_
from sqlalchemy.orm import Session

from app.db.time import local_today, utcnow
from app.models.category import Category
from app.models.financial_entry import FinancialEntry
from app.models.payable import PayableIdempotencyKey, PayableObligation, PayableSettlement
from app.models.user import User
from app.schemas.finance import format_money
from app.schemas.payable import (
    ObligationCreate,
    ObligationDetail,
    ObligationPage,
    ObligationPublic,
    ObligationUpdate,
    PayableSummary,
    PaymentCreate,
    PaymentPublic,
    SettlementPublic,
)
from app.services.audit_service import add_audit
from app.services.finance_service import (
    EXPENSE,
    FinanceError,
    IdempotencyConflict,
    _category_name,
    _financial_transaction,
    _insert_expense,
    _lock_accounts,
    _lock_categories,
    money,
)

PAYABLE_ENTITY = "payable_obligation"
PAID_OBLIGATION_MESSAGE = (
    "A obrigação já está paga. Altere a despesa vinculada ou exclua o pagamento "
    "antes de mudar valor, vencimento ou categoria."
)
ALLOCATION_MESSAGE = "Altere as parcelas do pagamento agrupado antes de mudar o valor."
RESTORE_CONFLICT_MESSAGE = "A obrigação já possui outra quitação válida."
RETRY_MESSAGE = "A conta a pagar foi alterada por outra operação. Repita a operação."


@dataclass(frozen=True)
class SettlementDraft:
    obligation_id: uuid.UUID
    allocated_amount: Decimal


@dataclass(frozen=True)
class LinkedPayables:
    obligations: dict[uuid.UUID, PayableObligation]
    settlements: list[PayableSettlement]

    @property
    def active(self) -> list[PayableSettlement]:
        return [item for item in self.settlements if item.released_at is None]


@dataclass(frozen=True)
class PaymentResult:
    payment: PaymentPublic
    replayed: bool


def create_obligation(db: Session, user: User, payload: ObligationCreate) -> ObligationDetail:
    amount = money(payload.expected_amount, positive=True)
    with _financial_transaction(db):
        if payload.category_id is not None:
            category = _lock_categories(db, user.id, [payload.category_id])[payload.category_id]
            _ensure_obligation_category(category)
        obligation = PayableObligation(
            user_id=user.id,
            description=payload.description,
            expected_amount=amount,
            due_on=payload.due_on,
            category_id=payload.category_id,
        )
        db.add(obligation)
        db.flush()
        add_audit(
            db,
            user_id=user.id,
            entity_type=PAYABLE_ENTITY,
            entity_id=obligation.id,
            operation="create",
            before=None,
            after=_obligation_snapshot(obligation, []),
        )
    db.refresh(obligation)
    return _detail(db, obligation)


def list_obligations(
    db: Session,
    user: User,
    *,
    status: str | None,
    due_from: date | None,
    due_to: date | None,
    include_archived: bool,
    limit: int,
    cursor: str | None,
) -> ObligationPage:
    if status not in {None, "open", "overdue", "paid", "archived"}:
        raise FinanceError(422, "Situação de conta a pagar inválida.")
    if due_from is not None and due_to is not None and due_from > due_to:
        raise FinanceError(422, "A data inicial não pode ser posterior à data final.")
    today = local_today()
    statement = select(PayableObligation).where(PayableObligation.user_id == user.id)
    active = exists(
        select(PayableSettlement.id).where(
            PayableSettlement.obligation_id == PayableObligation.id,
            PayableSettlement.released_at.is_(None),
        )
    )
    if status == "archived":
        statement = statement.where(PayableObligation.archived_at.is_not(None))
    elif status == "paid":
        statement = statement.where(PayableObligation.archived_at.is_(None), active)
    elif status == "overdue":
        statement = statement.where(
            PayableObligation.archived_at.is_(None),
            PayableObligation.due_on < today,
            ~active,
        )
    elif status == "open":
        statement = statement.where(
            PayableObligation.archived_at.is_(None),
            PayableObligation.due_on >= today,
            ~active,
        )
    elif not include_archived:
        statement = statement.where(PayableObligation.archived_at.is_(None))
    if due_from is not None:
        statement = statement.where(PayableObligation.due_on >= due_from)
    if due_to is not None:
        statement = statement.where(PayableObligation.due_on <= due_to)
    if cursor:
        day, obligation_id = _decode_cursor(cursor)
        statement = statement.where(
            tuple_(PayableObligation.due_on, PayableObligation.id) > tuple_(day, obligation_id)
        )
    statement = statement.order_by(PayableObligation.due_on, PayableObligation.id).limit(limit + 1)
    rows = list(db.scalars(statement))
    visible = rows[:limit]
    active_by_obligation = _active_map(db, [item.id for item in visible])
    names = _category_names(db, visible)
    items = [
        _public_obligation(item, names.get(item.category_id), active_by_obligation.get(item.id), today)
        for item in visible
    ]
    next_cursor = None
    if len(rows) > limit and visible:
        last = visible[-1]
        next_cursor = _encode_cursor(last.due_on, last.id)
    return ObligationPage(items=items, next_cursor=next_cursor)


def summarize_payables(db: Session, user: User) -> PayableSummary:
    today = local_today()
    open_expected = _expected_total(db, user.id, PayableObligation.due_on >= today)
    overdue_expected = _expected_total(db, user.id, PayableObligation.due_on < today)
    paid_amount = db.scalar(
        select(func.coalesce(func.sum(PayableSettlement.allocated_amount), 0))
        .select_from(PayableSettlement)
        .join(PayableObligation, PayableObligation.id == PayableSettlement.obligation_id)
        .where(
            PayableObligation.user_id == user.id,
            PayableObligation.archived_at.is_(None),
            PayableSettlement.released_at.is_(None),
        )
    )
    return PayableSummary(
        open_expected=format_money(Decimal(open_expected)),
        overdue_expected=format_money(Decimal(overdue_expected)),
        paid_amount=format_money(Decimal(paid_amount)),
    )


def _expected_total(db: Session, user_id: uuid.UUID, due_clause) -> Decimal:
    active = exists(
        select(PayableSettlement.id).where(
            PayableSettlement.obligation_id == PayableObligation.id,
            PayableSettlement.released_at.is_(None),
        )
    )
    total = db.scalar(
        select(func.coalesce(func.sum(PayableObligation.expected_amount), 0)).where(
            PayableObligation.user_id == user_id,
            PayableObligation.archived_at.is_(None),
            due_clause,
            ~active,
        )
    )
    return Decimal(total)


def get_obligation(db: Session, user: User, obligation_id: uuid.UUID) -> ObligationDetail:
    return _detail(db, _owned_obligation(db, user.id, obligation_id))


def update_obligation(
    db: Session,
    user: User,
    obligation_id: uuid.UUID,
    payload: ObligationUpdate,
) -> ObligationDetail:
    with _financial_transaction(db):
        if "category_id" in payload.model_fields_set and payload.category_id is not None:
            category = _lock_categories(db, user.id, [payload.category_id])[payload.category_id]
            _ensure_obligation_category(category)
        obligation = _lock_obligations(db, user.id, [obligation_id])[obligation_id]
        if obligation.archived_at is not None:
            raise FinanceError(409, "Reative a conta a pagar antes de editá-la.")
        settlements = _settlements_of(db, obligation.id)
        active = next((item for item in settlements if item.released_at is None), None)
        protected = {"expected_amount", "due_on", "category_id"} & set(payload.model_fields_set)
        if active is not None and protected:
            raise FinanceError(409, PAID_OBLIGATION_MESSAGE)
        before = _obligation_snapshot(obligation, settlements)
        if "description" in payload.model_fields_set:
            if payload.description is None:
                raise FinanceError(422, "Informe a descrição.")
            obligation.description = payload.description
        if "expected_amount" in payload.model_fields_set:
            if payload.expected_amount is None:
                raise FinanceError(422, "Informe o valor.")
            obligation.expected_amount = money(payload.expected_amount, positive=True)
        if "due_on" in payload.model_fields_set:
            if payload.due_on is None:
                raise FinanceError(422, "Informe o vencimento.")
            obligation.due_on = payload.due_on
        if "category_id" in payload.model_fields_set:
            obligation.category_id = payload.category_id
        obligation.updated_at = utcnow()
        after = _obligation_snapshot(obligation, settlements)
        if before == after:
            raise FinanceError(422, "Nenhuma alteração informada.")
        add_audit(
            db,
            user_id=user.id,
            entity_type=PAYABLE_ENTITY,
            entity_id=obligation.id,
            operation="update",
            before=before,
            after=after,
        )
    db.refresh(obligation)
    return _detail(db, obligation)


def archive_obligation(db: Session, user: User, obligation_id: uuid.UUID) -> ObligationDetail:
    return _set_archived(db, user, obligation_id, archived=True)


def reactivate_obligation(db: Session, user: User, obligation_id: uuid.UUID) -> ObligationDetail:
    return _set_archived(db, user, obligation_id, archived=False)


def pay_obligation(
    db: Session,
    user: User,
    obligation_id: uuid.UUID,
    payload: PaymentCreate,
    idempotency_key: str,
) -> PaymentResult:
    preview = _owned_obligation(db, user.id, obligation_id)
    amount = preview.expected_amount if payload.amount is None else money(payload.amount, positive=True)
    category_from_obligation = payload.category_id is None
    category_id = preview.category_id if category_from_obligation else payload.category_id
    description = preview.description if payload.description is None else payload.description
    return settle_obligations(
        db,
        user,
        account_id=payload.account_id,
        category_id=category_id,
        occurred_on=payload.occurred_on or local_today(),
        description=description,
        items=[SettlementDraft(obligation_id, amount)],
        idempotency_key=idempotency_key,
        category_from_obligation=category_from_obligation,
    )


def settle_obligations(
    db: Session,
    user: User,
    *,
    account_id: uuid.UUID,
    category_id: uuid.UUID | None,
    occurred_on: date,
    description: str | None,
    items: list[SettlementDraft],
    idempotency_key: str,
    category_from_obligation: bool = False,
) -> PaymentResult:
    key = _clean_key(idempotency_key)
    if not items:
        raise FinanceError(422, "Informe ao menos uma obrigação.")
    if category_id is None:
        raise FinanceError(422, "Informe a categoria.")
    drafts = _normalize_drafts(items)
    digest = _request_hash(
        account_id=account_id,
        category_id=category_id,
        occurred_on=occurred_on,
        description=description,
        items=drafts,
    )
    try:
        with _financial_transaction(db):
            return _settle_locked(
                db,
                user,
                account_id=account_id,
                category_id=category_id,
                occurred_on=occurred_on,
                description=description,
                items=drafts,
                key=key,
                digest=digest,
                entry_id=uuid.uuid4(),
                category_from_obligation=category_from_obligation,
            )
    except IdempotencyConflict:
        return _replay_from_conflict(db, user, key, digest)


def lock_linked_obligations(db: Session, user: User, entry: FinancialEntry) -> LinkedPayables:
    obligation_ids = list(
        db.scalars(
            select(PayableSettlement.obligation_id).where(
                PayableSettlement.user_id == user.id,
                PayableSettlement.entry_id == entry.id,
            )
        )
    )
    if not obligation_ids:
        return LinkedPayables({}, [])
    obligations = _lock_obligations(db, user.id, obligation_ids)
    return LinkedPayables(obligations, _settlements_for_entry(db, user.id, entry.id))


def sync_linked_allocation(
    db: Session,
    user: User,
    entry: FinancialEntry,
    linked: LinkedPayables,
    previous_amount: Decimal,
) -> None:
    if entry.amount == previous_amount or not linked.active:
        return
    if len(linked.active) != 1:
        raise FinanceError(409, ALLOCATION_MESSAGE)
    settlement = linked.active[0]
    obligation = linked.obligations[settlement.obligation_id]
    history = _history(linked, obligation.id)
    before = _obligation_snapshot(obligation, history)
    settlement.allocated_amount = entry.amount
    obligation.updated_at = utcnow()
    add_audit(
        db,
        user_id=user.id,
        entity_type=PAYABLE_ENTITY,
        entity_id=obligation.id,
        operation="update",
        before=before,
        after=_obligation_snapshot(obligation, history),
    )


def release_linked_settlements(db: Session, user: User, entry: FinancialEntry, linked: LinkedPayables) -> None:
    released_at = utcnow()
    for settlement in linked.active:
        obligation = linked.obligations[settlement.obligation_id]
        history = _history(linked, obligation.id)
        before = _obligation_snapshot(obligation, history)
        settlement.released_at = released_at
        obligation.updated_at = released_at
        add_audit(
            db,
            user_id=user.id,
            entity_type=PAYABLE_ENTITY,
            entity_id=obligation.id,
            operation="release",
            before=before,
            after=_obligation_snapshot(obligation, history),
        )


def claim_linked_restore(db: Session, user: User, entry: FinancialEntry) -> LinkedPayables:
    linked = lock_linked_obligations(db, user, entry)
    for settlement in linked.settlements:
        if settlement.released_at is None:
            continue
        other = db.scalar(
            select(PayableSettlement.id).where(
                PayableSettlement.obligation_id == settlement.obligation_id,
                PayableSettlement.released_at.is_(None),
                PayableSettlement.id != settlement.id,
            )
        )
        if other is not None:
            raise FinanceError(409, RESTORE_CONFLICT_MESSAGE)
    return linked


def finish_linked_restore(db: Session, user: User, linked: LinkedPayables) -> None:
    restored_at = utcnow()
    for settlement in linked.settlements:
        if settlement.released_at is None:
            continue
        obligation = linked.obligations[settlement.obligation_id]
        history = _history(linked, obligation.id)
        before = _obligation_snapshot(obligation, history)
        settlement.released_at = None
        obligation.updated_at = restored_at
        add_audit(
            db,
            user_id=user.id,
            entity_type=PAYABLE_ENTITY,
            entity_id=obligation.id,
            operation="restore",
            before=before,
            after=_obligation_snapshot(obligation, history),
        )


def _settle_locked(
    db: Session,
    user: User,
    *,
    account_id: uuid.UUID,
    category_id: uuid.UUID,
    occurred_on: date,
    description: str | None,
    items: list[SettlementDraft],
    key: str,
    digest: str,
    entry_id: uuid.UUID,
    category_from_obligation: bool,
) -> PaymentResult:
    account = _lock_accounts(db, user.id, [account_id])[account_id]
    category = _lock_categories(db, user.id, [category_id])[category_id]
    stored = _lock_idempotency_key(db, user.id, key)
    if stored is not None:
        return _payment_from_stored_key(db, user, stored, digest)
    primary_id = items[0].obligation_id
    db.add(
        PayableIdempotencyKey(
            user_id=user.id,
            idempotency_key=key,
            request_hash=digest,
            obligation_id=primary_id,
            entry_id=entry_id,
        )
    )
    db.flush()
    obligations = _lock_obligations(db, user.id, [item.obligation_id for item in items])
    if category_from_obligation:
        for item in items:
            if obligations[item.obligation_id].category_id != category_id:
                raise FinanceError(409, RETRY_MESSAGE)
    for item in items:
        obligation = obligations[item.obligation_id]
        if obligation.archived_at is not None:
            raise FinanceError(409, "A conta a pagar arquivada não aceita pagamento.")
        if any(row.released_at is None for row in _settlements_of(db, obligation.id)):
            raise FinanceError(409, "A obrigação já está paga.")
    total = money(sum((item.allocated_amount for item in items), Decimal("0.00")), positive=True)
    entry = _insert_expense(
        db,
        user,
        account=account,
        category=category,
        amount=total,
        occurred_on=occurred_on,
        description=description,
        entry_id=entry_id,
        kind=EXPENSE,
    )
    paid_at = utcnow()
    first_settlement_id: uuid.UUID | None = None
    for item in items:
        obligation = obligations[item.obligation_id]
        history = _settlements_of(db, obligation.id)
        before = _obligation_snapshot(obligation, history)
        settlement = PayableSettlement(
            user_id=user.id,
            obligation_id=obligation.id,
            entry_id=entry.id,
            allocated_amount=item.allocated_amount,
        )
        db.add(settlement)
        db.flush()
        if first_settlement_id is None:
            first_settlement_id = settlement.id
        obligation.updated_at = paid_at
        add_audit(
            db,
            user_id=user.id,
            entity_type=PAYABLE_ENTITY,
            entity_id=obligation.id,
            operation="pay",
            before=before,
            after=_obligation_snapshot(obligation, history + [settlement]),
        )
    if first_settlement_id is None:
        raise FinanceError(422, "Informe ao menos uma obrigação.")
    return PaymentResult(
        payment=PaymentPublic(
            obligation=_detail(db, obligations[primary_id]),
            entry_id=entry.id,
            settlement_id=first_settlement_id,
            amount=format_money(entry.amount),
            replayed=False,
        ),
        replayed=False,
    )


def _replay_from_conflict(db: Session, user: User, key: str, digest: str) -> PaymentResult:
    stored = db.scalar(
        select(PayableIdempotencyKey).where(
            PayableIdempotencyKey.user_id == user.id,
            PayableIdempotencyKey.idempotency_key == key,
        )
    )
    if stored is None:
        raise FinanceError(409, "Conflito ao gravar os dados financeiros.")
    return _payment_from_stored_key(db, user, stored, digest)


def _payment_from_stored_key(
    db: Session,
    user: User,
    stored: PayableIdempotencyKey,
    digest: str,
) -> PaymentResult:
    if stored.request_hash != digest:
        raise FinanceError(409, "Esta chave já foi usada com outros dados.")
    entry = db.scalar(
        select(FinancialEntry).where(
            FinancialEntry.id == stored.entry_id,
            FinancialEntry.user_id == user.id,
        )
    )
    settlement = db.scalar(
        select(PayableSettlement).where(
            PayableSettlement.user_id == user.id,
            PayableSettlement.entry_id == stored.entry_id,
            PayableSettlement.obligation_id == stored.obligation_id,
        )
    )
    if entry is None or settlement is None:
        raise FinanceError(409, "Conflito ao gravar os dados financeiros.")
    obligation = _owned_obligation(db, user.id, stored.obligation_id)
    return PaymentResult(
        payment=PaymentPublic(
            obligation=_detail(db, obligation),
            entry_id=entry.id,
            settlement_id=settlement.id,
            amount=format_money(entry.amount),
            replayed=True,
        ),
        replayed=True,
    )


def _set_archived(db: Session, user: User, obligation_id: uuid.UUID, *, archived: bool) -> ObligationDetail:
    with _financial_transaction(db):
        obligation = _lock_obligations(db, user.id, [obligation_id])[obligation_id]
        settlements = _settlements_of(db, obligation.id)
        if archived and obligation.archived_at is not None:
            raise FinanceError(409, "A conta a pagar já está arquivada.")
        if not archived and obligation.archived_at is None:
            raise FinanceError(409, "A conta a pagar não está arquivada.")
        before = _obligation_snapshot(obligation, settlements)
        moment = utcnow()
        obligation.archived_at = moment if archived else None
        obligation.updated_at = moment
        add_audit(
            db,
            user_id=user.id,
            entity_type=PAYABLE_ENTITY,
            entity_id=obligation.id,
            operation="archive" if archived else "reactivate",
            before=before,
            after=_obligation_snapshot(obligation, settlements),
        )
    db.refresh(obligation)
    return _detail(db, obligation)


def _normalize_drafts(items: list[SettlementDraft]) -> list[SettlementDraft]:
    seen: set[uuid.UUID] = set()
    drafts: list[SettlementDraft] = []
    for item in items:
        if item.obligation_id in seen:
            raise FinanceError(422, "A mesma obrigação foi informada mais de uma vez.")
        seen.add(item.obligation_id)
        drafts.append(SettlementDraft(item.obligation_id, money(item.allocated_amount, positive=True)))
    return sorted(drafts, key=lambda item: item.obligation_id)


def _request_hash(
    *,
    account_id: uuid.UUID,
    category_id: uuid.UUID,
    occurred_on: date,
    description: str | None,
    items: list[SettlementDraft],
) -> str:
    parts = [str(account_id), str(category_id), occurred_on.isoformat(), description or ""]
    for item in items:
        parts.append(f"{item.obligation_id}:{format_money(item.allocated_amount)}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _clean_key(value: str) -> str:
    key = value.strip()
    if not key or key != value or len(key) > 64 or any(character.isspace() for character in key):
        raise FinanceError(422, "Informe uma chave de idempotência de 1 a 64 caracteres.")
    return key


def _lock_idempotency_key(db: Session, user_id: uuid.UUID, key: str) -> PayableIdempotencyKey | None:
    return db.scalar(
        select(PayableIdempotencyKey)
        .where(
            PayableIdempotencyKey.user_id == user_id,
            PayableIdempotencyKey.idempotency_key == key,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _lock_obligations(
    db: Session,
    user_id: uuid.UUID,
    obligation_ids: list[uuid.UUID],
) -> dict[uuid.UUID, PayableObligation]:
    locked: dict[uuid.UUID, PayableObligation] = {}
    for obligation_id in sorted(set(obligation_ids)):
        obligation = db.scalar(
            select(PayableObligation)
            .where(PayableObligation.id == obligation_id, PayableObligation.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if obligation is None:
            raise FinanceError(404, "Conta a pagar não encontrada.")
        locked[obligation_id] = obligation
    return locked


def _owned_obligation(db: Session, user_id: uuid.UUID, obligation_id: uuid.UUID) -> PayableObligation:
    obligation = db.scalar(
        select(PayableObligation).where(
            PayableObligation.id == obligation_id,
            PayableObligation.user_id == user_id,
        )
    )
    if obligation is None:
        raise FinanceError(404, "Conta a pagar não encontrada.")
    return obligation


def _ensure_obligation_category(category: Category) -> None:
    if category.is_internal:
        raise FinanceError(422, "A categoria interna não pode ser usada em contas a pagar.")


def _active_map(db: Session, obligation_ids: list[uuid.UUID]) -> dict[uuid.UUID, PayableSettlement]:
    if not obligation_ids:
        return {}
    rows = db.scalars(
        select(PayableSettlement).where(
            PayableSettlement.obligation_id.in_(obligation_ids),
            PayableSettlement.released_at.is_(None),
        )
    )
    return {row.obligation_id: row for row in rows}


def _settlements_of(db: Session, obligation_id: uuid.UUID) -> list[PayableSettlement]:
    return list(
        db.scalars(
            select(PayableSettlement)
            .where(PayableSettlement.obligation_id == obligation_id)
            .order_by(PayableSettlement.created_at, PayableSettlement.id)
            .execution_options(populate_existing=True)
        )
    )


def _settlements_for_entry(db: Session, user_id: uuid.UUID, entry_id: uuid.UUID) -> list[PayableSettlement]:
    return list(
        db.scalars(
            select(PayableSettlement)
            .where(PayableSettlement.user_id == user_id, PayableSettlement.entry_id == entry_id)
            .order_by(PayableSettlement.created_at, PayableSettlement.id)
            .execution_options(populate_existing=True)
        )
    )


def _detail(db: Session, obligation: PayableObligation) -> ObligationDetail:
    settlements = _settlements_of(db, obligation.id)
    active = next((item for item in settlements if item.released_at is None), None)
    public = _public_obligation(
        obligation,
        _category_name(db, obligation.category_id),
        active,
        local_today(),
    )
    entry_ids = [item.entry_id for item in settlements]
    entries = {}
    if entry_ids:
        entries = {
            entry.id: entry
            for entry in db.scalars(select(FinancialEntry).where(FinancialEntry.id.in_(entry_ids)))
        }
    history = [
        SettlementPublic(
            id=item.id,
            obligation_id=item.obligation_id,
            entry_id=item.entry_id,
            allocated_amount=format_money(item.allocated_amount),
            released_at=item.released_at,
            entry_deleted_at=entries[item.entry_id].deleted_at,
            entry_occurred_on=entries[item.entry_id].occurred_on,
            entry_account_id=entries[item.entry_id].account_id,
            created_at=item.created_at,
        )
        for item in settlements
    ]
    return ObligationDetail(**public.model_dump(), settlements=history)


def _public_obligation(
    obligation: PayableObligation,
    category_name: str | None,
    active: PayableSettlement | None,
    today: date,
) -> ObligationPublic:
    if obligation.archived_at is not None:
        status = "archived"
    elif active is not None:
        status = "paid"
    elif obligation.due_on < today:
        status = "overdue"
    else:
        status = "open"
    return ObligationPublic(
        id=obligation.id,
        description=obligation.description,
        expected_amount=format_money(obligation.expected_amount),
        due_on=obligation.due_on,
        category_id=obligation.category_id,
        category_name=category_name,
        status=status,
        archived_at=obligation.archived_at,
        active_settlement_id=active.id if active is not None else None,
        paid_amount=format_money(active.allocated_amount) if active is not None else None,
        created_at=obligation.created_at,
        updated_at=obligation.updated_at,
    )


def _category_names(db: Session, obligations: list[PayableObligation]) -> dict[uuid.UUID, str]:
    identifiers = {item.category_id for item in obligations if item.category_id is not None}
    if not identifiers:
        return {}
    rows = db.execute(select(Category.id, Category.name).where(Category.id.in_(identifiers))).all()
    return {row.id: row.name for row in rows}


def _history(linked: LinkedPayables, obligation_id: uuid.UUID) -> list[PayableSettlement]:
    return [item for item in linked.settlements if item.obligation_id == obligation_id]


def _obligation_snapshot(obligation: PayableObligation, settlements: list[PayableSettlement]) -> dict[str, Any]:
    return {
        "id": str(obligation.id),
        "description": obligation.description,
        "expected_amount": format_money(obligation.expected_amount),
        "due_on": obligation.due_on.isoformat(),
        "category_id": str(obligation.category_id) if obligation.category_id else None,
        "archived_at": obligation.archived_at.isoformat() if obligation.archived_at else None,
        "settlements": [
            {
                "id": str(item.id),
                "entry_id": str(item.entry_id),
                "allocated_amount": format_money(item.allocated_amount),
                "released_at": item.released_at.isoformat() if item.released_at else None,
            }
            for item in settlements
        ],
    }


def _encode_cursor(due_on: date, obligation_id: uuid.UUID) -> str:
    payload = f"{due_on.isoformat()}|{obligation_id}"
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[date, uuid.UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        day, obligation_id = raw.split("|", 1)
        return date.fromisoformat(day), uuid.UUID(obligation_id)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise FinanceError(422, "Cursor inválido.") from None
