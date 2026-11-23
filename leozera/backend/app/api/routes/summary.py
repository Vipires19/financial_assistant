from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, run_finance
from app.db.session import get_db
from app.models.user import User
from app.schemas.finance import SummaryPublic
from app.services.finance_service import get_summary

router = APIRouter(prefix="/summary", tags=["summary"])


@router.get("", response_model=SummaryPublic)
def get_finance_summary(
    occurred_from: date | None = None,
    occurred_to: date | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SummaryPublic:
    return run_finance(
        lambda: get_summary(
            db,
            current_user,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
        )
    )
