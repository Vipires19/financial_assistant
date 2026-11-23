from collections.abc import Callable
from typing import TypeVar

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.cookies import enforce_session_csrf
from app.core.config import get_settings
from app.db.session import get_db
from app.models.auth_session import AuthSession
from app.models.user import User
from app.services.auth_service import get_active_session

T = TypeVar("T")


def get_auth_session(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthSession:
    token = request.cookies.get(get_settings().session_cookie_name)
    auth_session = get_active_session(db, token)
    if auth_session is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    return auth_session


def _load_user(auth_session: AuthSession, db: Session) -> User:
    user = db.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    return user


def get_current_user(
    auth_session: AuthSession = Depends(get_auth_session),
    db: Session = Depends(get_db),
) -> User:
    return _load_user(auth_session, db)


def require_csrf_user(
    request: Request,
    auth_session: AuthSession = Depends(get_auth_session),
    db: Session = Depends(get_db),
) -> User:
    enforce_session_csrf(request, auth_session)
    return _load_user(auth_session, db)


def run_finance(action: Callable[[], T]) -> T:
    from app.services.finance_service import FinanceError

    try:
        return action()
    except FinanceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
