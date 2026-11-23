import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_csrf_user, run_finance
from app.db.session import get_db
from app.models.user import User
from app.schemas.finance import EntryPublic, TransferCreate, TransferUpdate
from app.services.finance_service import (
    create_transfer,
    delete_transfer,
    restore_transfer,
    update_transfer,
)

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.post("", response_model=EntryPublic, status_code=201)
def post_transfer(
    payload: TransferCreate,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> EntryPublic:
    return run_finance(lambda: create_transfer(db, current_user, payload))


@router.patch("/{entry_id}", response_model=EntryPublic)
def patch_transfer(
    entry_id: uuid.UUID,
    payload: TransferUpdate,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> EntryPublic:
    return run_finance(lambda: update_transfer(db, current_user, entry_id, payload))


@router.delete("/{entry_id}", response_model=EntryPublic)
def remove_transfer(
    entry_id: uuid.UUID,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> EntryPublic:
    return run_finance(lambda: delete_transfer(db, current_user, entry_id))


@router.post("/{entry_id}/restore", response_model=EntryPublic)
def post_restore_transfer(
    entry_id: uuid.UUID,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> EntryPublic:
    return run_finance(lambda: restore_transfer(db, current_user, entry_id))
