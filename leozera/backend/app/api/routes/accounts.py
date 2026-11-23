import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf_user, run_finance
from app.db.session import get_db
from app.models.user import User
from app.schemas.finance import (
    AccountCreate,
    AccountPublic,
    AccountUpdate,
    AdjustmentCreate,
    AdjustmentUpdate,
    BalancePublic,
    EntryPublic,
)
from app.services.finance_service import (
    archive_account,
    create_account,
    create_adjustment,
    delete_adjustment,
    get_account,
    get_account_balance,
    list_accounts,
    reactivate_account,
    restore_adjustment,
    update_account,
    update_adjustment,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountPublic])
def get_accounts(
    include_archived: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AccountPublic]:
    return run_finance(lambda: list_accounts(db, current_user, include_archived=include_archived))


@router.post("", response_model=AccountPublic, status_code=201)
def post_account(
    payload: AccountCreate,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> AccountPublic:
    return run_finance(lambda: create_account(db, current_user, payload))


@router.get("/{account_id}", response_model=AccountPublic)
def get_one_account(
    account_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccountPublic:
    return run_finance(lambda: get_account(db, current_user, account_id))


@router.patch("/{account_id}", response_model=AccountPublic)
def patch_account(
    account_id: uuid.UUID,
    payload: AccountUpdate,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> AccountPublic:
    return run_finance(lambda: update_account(db, current_user, account_id, payload))


@router.post("/{account_id}/archive", response_model=AccountPublic)
def post_archive_account(
    account_id: uuid.UUID,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> AccountPublic:
    return run_finance(lambda: archive_account(db, current_user, account_id))


@router.post("/{account_id}/reactivate", response_model=AccountPublic)
def post_reactivate_account(
    account_id: uuid.UUID,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> AccountPublic:
    return run_finance(lambda: reactivate_account(db, current_user, account_id))


@router.get("/{account_id}/balance", response_model=BalancePublic)
def get_balance(
    account_id: uuid.UUID,
    on: date | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BalancePublic:
    return run_finance(lambda: get_account_balance(db, current_user, account_id, on))


@router.post("/{account_id}/adjustments", response_model=EntryPublic, status_code=201)
def post_adjustment(
    account_id: uuid.UUID,
    payload: AdjustmentCreate,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> EntryPublic:
    return run_finance(lambda: create_adjustment(db, current_user, account_id, payload))


@router.patch("/{account_id}/adjustments/{adjustment_id}", response_model=EntryPublic)
def patch_adjustment(
    account_id: uuid.UUID,
    adjustment_id: uuid.UUID,
    payload: AdjustmentUpdate,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> EntryPublic:
    return run_finance(
        lambda: update_adjustment(db, current_user, account_id, adjustment_id, payload)
    )


@router.delete("/{account_id}/adjustments/{adjustment_id}", response_model=EntryPublic)
def remove_adjustment(
    account_id: uuid.UUID,
    adjustment_id: uuid.UUID,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> EntryPublic:
    return run_finance(lambda: delete_adjustment(db, current_user, account_id, adjustment_id))


@router.post("/{account_id}/adjustments/{adjustment_id}/restore", response_model=EntryPublic)
def post_restore_adjustment(
    account_id: uuid.UUID,
    adjustment_id: uuid.UUID,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> EntryPublic:
    return run_finance(lambda: restore_adjustment(db, current_user, account_id, adjustment_id))
