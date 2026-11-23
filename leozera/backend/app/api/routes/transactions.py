import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf_user, run_finance
from app.db.session import get_db
from app.models.user import User
from app.schemas.finance import EntryPage, EntryPublic, TransactionCreate, TransactionUpdate
from app.services.finance_service import (
    create_transaction,
    delete_transaction,
    get_transaction,
    list_transactions,
    restore_transaction,
    update_transaction,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=EntryPage)
def get_transactions(
    account_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    kind: Literal["income", "expense", "transfer", "adjustment"] | None = None,
    occurred_from: date | None = None,
    occurred_to: date | None = None,
    description: str | None = Query(default=None, max_length=500),
    include_deleted: bool = False,
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EntryPage:
    return run_finance(
        lambda: list_transactions(
            db,
            current_user,
            account_id=account_id,
            category_id=category_id,
            kind=kind,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
            description=description,
            include_deleted=include_deleted,
            order=order,
            limit=limit,
            cursor=cursor,
        )
    )


@router.post("", response_model=EntryPublic, status_code=201)
def post_transaction(
    payload: TransactionCreate,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> EntryPublic:
    return run_finance(lambda: create_transaction(db, current_user, payload))


@router.get("/{entry_id}", response_model=EntryPublic)
def get_one_transaction(
    entry_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EntryPublic:
    return run_finance(lambda: get_transaction(db, current_user, entry_id))


@router.patch("/{entry_id}", response_model=EntryPublic)
def patch_transaction(
    entry_id: uuid.UUID,
    payload: TransactionUpdate,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> EntryPublic:
    return run_finance(lambda: update_transaction(db, current_user, entry_id, payload))


@router.delete("/{entry_id}", response_model=EntryPublic)
def remove_transaction(
    entry_id: uuid.UUID,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> EntryPublic:
    return run_finance(lambda: delete_transaction(db, current_user, entry_id))


@router.post("/{entry_id}/restore", response_model=EntryPublic)
def post_restore_transaction(
    entry_id: uuid.UUID,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> EntryPublic:
    return run_finance(lambda: restore_transaction(db, current_user, entry_id))
