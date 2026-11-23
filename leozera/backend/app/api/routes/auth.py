from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_auth_session, get_current_user
from app.auth.cookies import clear_auth_cookies, enforce_session_csrf, set_auth_cookies
from app.db.session import get_db
from app.models.auth_session import AuthSession
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, UserPublic
from app.services.auth_service import AuthError, authenticate, register_user, revoke_session

router = APIRouter(prefix="/auth")


@router.post("/register", response_model=UserPublic, status_code=201)
def register(
    payload: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> User:
    try:
        user, raw_session, raw_csrf = register_user(db, payload)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    set_auth_cookies(response, raw_session, raw_csrf)
    return user


@router.post("/login", response_model=UserPublic)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> User:
    try:
        user, raw_session, raw_csrf = authenticate(db, payload)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    set_auth_cookies(response, raw_session, raw_csrf)
    return user


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    auth_session: AuthSession = Depends(get_auth_session),
    db: Session = Depends(get_db),
) -> Response:
    enforce_session_csrf(request, auth_session)
    revoke_session(db, auth_session)
    response = Response(status_code=204)
    clear_auth_cookies(response)
    return response


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
