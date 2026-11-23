import secrets

from fastapi import HTTPException, Request, Response

from app.auth.tokens import hash_token
from app.core.config import get_settings
from app.models.auth_session import AuthSession


def set_auth_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=settings.session_ttl_seconds,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=False,
        samesite="lax",
    )


def enforce_session_csrf(request: Request, auth_session: AuthSession) -> None:
    header = request.headers.get("x-csrf-token")
    if not header:
        raise HTTPException(status_code=403, detail="Falha na verificação CSRF.")
    presented = hash_token(header.strip())
    if not secrets.compare_digest(presented, auth_session.csrf_token_hash):
        raise HTTPException(status_code=403, detail="Falha na verificação CSRF.")
