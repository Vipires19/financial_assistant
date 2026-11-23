from datetime import timedelta

from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.time import utcnow
from app.models.auth_session import AuthSession
from app.models.user import User
from tests.conftest import auth_headers

USER = {
    "name": "André",
    "email": "andre@example.com",
    "password": "senha-segura-1",
}


def register(client, payload=None, headers=None):
    return client.post("/auth/register", json=payload or USER, headers=headers or auth_headers())


def test_register_valid(client):
    response = register(client)
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "André"
    assert body["email"] == "andre@example.com"
    assert "hashed_password" not in body
    assert "password" not in body
    assert "leozera_session" in response.cookies
    assert "leozera_csrf" in response.cookies


def test_register_normalizes_email(client):
    payload = {**USER, "email": "  Andre@Example.com "}
    response = register(client, payload)
    assert response.status_code == 201
    assert response.json()["email"] == "andre@example.com"


def test_register_duplicate_email(client):
    assert register(client).status_code == 201
    response = register(client, {**USER, "email": "ANDRE@example.com"})
    assert response.status_code == 409
    assert "hashed_password" not in response.text


def test_register_validation_error(client):
    response = register(client, {"name": "", "email": "invalido", "password": "curta"})
    assert response.status_code == 422


def test_login_valid_and_me(client):
    register(client)
    client.cookies.clear()
    response = client.post(
        "/auth/login",
        json={"email": "andre@example.com", "password": "senha-segura-1"},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["name"] == "André"
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "andre@example.com"


def test_login_invalid(client):
    register(client)
    client.cookies.clear()
    response = client.post(
        "/auth/login",
        json={"email": "andre@example.com", "password": "senha-errada-1"},
        headers=auth_headers(),
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Email ou senha inválidos."


def test_me_requires_authentication(client):
    assert client.get("/auth/me").status_code == 401


def test_logout_revokes_session(client):
    registered = register(client)
    csrf = registered.cookies["leozera_csrf"]
    response = client.post("/auth/logout", headers=auth_headers(csrf))
    assert response.status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_expired_session_is_rejected(client):
    register(client)
    db = SessionLocal()
    try:
        auth_session = db.scalar(select(AuthSession))
        auth_session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    assert client.get("/auth/me").status_code == 401


def test_revoked_session_is_rejected(client):
    register(client)
    db = SessionLocal()
    try:
        auth_session = db.scalar(select(AuthSession))
        auth_session.revoked_at = utcnow()
        db.commit()
    finally:
        db.close()
    assert client.get("/auth/me").status_code == 401


def test_inactive_user_is_rejected(client):
    register(client)
    db = SessionLocal()
    try:
        user = db.scalar(select(User))
        user.is_active = False
        db.commit()
    finally:
        db.close()
    assert client.get("/auth/me").status_code == 401
    client.cookies.clear()
    response = client.post(
        "/auth/login",
        json={"email": USER["email"], "password": USER["password"]},
        headers=auth_headers(),
    )
    assert response.status_code == 401


def test_sessions_are_isolated(client):
    from fastapi.testclient import TestClient

    from app.main import app

    first = register(client)
    with TestClient(app) as other:
        second = other.post(
            "/auth/register",
            json={"name": "Bia", "email": "bia@example.com", "password": "senha-segura-2"},
            headers=auth_headers(),
        )
        assert second.status_code == 201
        assert client.get("/auth/me").json()["email"] == "andre@example.com"
        assert other.get("/auth/me").json()["email"] == "bia@example.com"
        other.cookies.set("leozera_session", first.cookies["leozera_session"])
        assert other.get("/auth/me").json()["email"] == "andre@example.com"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
