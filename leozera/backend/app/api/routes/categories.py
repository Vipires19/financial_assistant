import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf_user, run_finance
from app.db.session import get_db
from app.models.user import User
from app.schemas.finance import CategoryCreate, CategoryPublic, CategoryUpdate
from app.services.finance_service import (
    archive_category,
    create_category,
    list_categories,
    reactivate_category,
    update_category,
)

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryPublic])
def get_categories(
    include_archived: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CategoryPublic]:
    return run_finance(
        lambda: list_categories(db, current_user, include_archived=include_archived)
    )


@router.post("", response_model=CategoryPublic, status_code=201)
def post_category(
    payload: CategoryCreate,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> CategoryPublic:
    return run_finance(lambda: create_category(db, current_user, payload))


@router.patch("/{category_id}", response_model=CategoryPublic)
def patch_category(
    category_id: uuid.UUID,
    payload: CategoryUpdate,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> CategoryPublic:
    return run_finance(lambda: update_category(db, current_user, category_id, payload))


@router.post("/{category_id}/archive", response_model=CategoryPublic)
def post_archive_category(
    category_id: uuid.UUID,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> CategoryPublic:
    return run_finance(lambda: archive_category(db, current_user, category_id))


@router.post("/{category_id}/reactivate", response_model=CategoryPublic)
def post_reactivate_category(
    category_id: uuid.UUID,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> CategoryPublic:
    return run_finance(lambda: reactivate_category(db, current_user, category_id))
