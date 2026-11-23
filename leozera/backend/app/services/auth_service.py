from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password, verify_password
from app.auth.tokens import generate_token, hash_token
from app.core.config import get_settings
from app.db.time import utcnow
from app.models.auth_session import AuthSession
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services.finance_service import provision_user_finance


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def register_user(db: Session, payload: RegisterRequest) -> tuple[User, str, str]:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise AuthError(409, "Este email já está cadastrado.")

    user = User(
        name=payload.name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise AuthError(409, "Este email já está cadastrado.") from None

    provision_user_finance(db, user)
    raw_session, raw_csrf = open_session(db, user)
    db.commit()
    db.refresh(user)
    return user, raw_session, raw_csrf


def authenticate(db: Session, payload: LoginRequest) -> tuple[User, str, str]:
    user = db.scalar(select(User).where(User.email == payload.email))
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.hashed_password)
    ):
        raise AuthError(401, "Email ou senha inválidos.")

    raw_session, raw_csrf = open_session(db, user)
    db.commit()
    db.refresh(user)
    return user, raw_session, raw_csrf


def open_session(db: Session, user: User) -> tuple[str, str]:
    raw_session = generate_token()
    raw_csrf = generate_token()
    now = utcnow()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(raw_session),
            csrf_token_hash=hash_token(raw_csrf),
            created_at=now,
            expires_at=now + timedelta(seconds=get_settings().session_ttl_seconds),
        )
    )
    return raw_session, raw_csrf


def get_active_session(db: Session, raw_token: str | None) -> AuthSession | None:
    if not raw_token:
        return None
    return db.scalar(
        select(AuthSession)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.token_hash == hash_token(raw_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
            User.is_active.is_(True),
        )
    )


def revoke_session(db: Session, auth_session: AuthSession) -> None:
    auth_session.revoked_at = utcnow()
    db.commit()
