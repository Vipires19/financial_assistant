import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_csrf_user, run_finance
from app.db.session import get_db
from app.models.user import User
from app.schemas.payable import (
    ObligationCreate,
    ObligationDetail,
    ObligationPage,
    ObligationUpdate,
    PayableSummary,
    PaymentCreate,
    PaymentPublic,
)
from app.services.payable_service import (
    archive_obligation,
    create_obligation,
    get_obligation,
    list_obligations,
    pay_obligation,
    reactivate_obligation,
    summarize_payables,
    update_obligation,
)

router = APIRouter(prefix="/payables", tags=["payables"])


@router.get("", response_model=ObligationPage)
def get_payables(
    status: Literal["open", "overdue", "paid", "archived"] | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ObligationPage:
    return run_finance(
        lambda: list_obligations(
            db,
            current_user,
            status=status,
            due_from=due_from,
            due_to=due_to,
            include_archived=include_archived,
            limit=limit,
            cursor=cursor,
        )
    )


@router.post("", response_model=ObligationDetail, status_code=201)
def post_payable(
    payload: ObligationCreate,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> ObligationDetail:
    return run_finance(lambda: create_obligation(db, current_user, payload))


@router.get("/summary", response_model=PayableSummary)
def get_payable_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PayableSummary:
    return run_finance(lambda: summarize_payables(db, current_user))


@router.get("/{obligation_id}", response_model=ObligationDetail)
def get_one_payable(
    obligation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ObligationDetail:
    return run_finance(lambda: get_obligation(db, current_user, obligation_id))


@router.patch("/{obligation_id}", response_model=ObligationDetail)
def patch_payable(
    obligation_id: uuid.UUID,
    payload: ObligationUpdate,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> ObligationDetail:
    return run_finance(lambda: update_obligation(db, current_user, obligation_id, payload))


@router.post("/{obligation_id}/archive", response_model=ObligationDetail)
def post_archive_payable(
    obligation_id: uuid.UUID,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> ObligationDetail:
    return run_finance(lambda: archive_obligation(db, current_user, obligation_id))


@router.post("/{obligation_id}/reactivate", response_model=ObligationDetail)
def post_reactivate_payable(
    obligation_id: uuid.UUID,
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> ObligationDetail:
    return run_finance(lambda: reactivate_obligation(db, current_user, obligation_id))


@router.post("/{obligation_id}/payments", response_model=PaymentPublic, status_code=201)
def post_payable_payment(
    obligation_id: uuid.UUID,
    payload: PaymentCreate,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    current_user: User = Depends(require_csrf_user),
    db: Session = Depends(get_db),
) -> PaymentPublic:
    result = run_finance(
        lambda: pay_obligation(db, current_user, obligation_id, payload, idempotency_key)
    )
    if result.replayed:
        response.status_code = 200
    return result.payment
