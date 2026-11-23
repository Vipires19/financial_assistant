from tests.conftest import ORIGIN, auth_headers
from tests.test_auth import USER, register


def test_register_rejects_missing_origin(client):
    response = client.post("/auth/register", json=USER)
    assert response.status_code == 403


def test_register_rejects_foreign_origin(client):
    response = register(client, headers=auth_headers(origin="https://evil.example"))
    assert response.status_code == 403


def test_login_accepts_referer_without_origin(client):
    register(client)
    client.cookies.clear()
    response = client.post(
        "/auth/login",
        json={"email": USER["email"], "password": USER["password"]},
        headers={"Referer": f"{ORIGIN}/login"},
    )
    assert response.status_code == 200


def test_login_rejects_foreign_referer(client):
    register(client)
    client.cookies.clear()
    response = client.post(
        "/auth/login",
        json={"email": USER["email"], "password": USER["password"]},
        headers={"Referer": "https://evil.example/login"},
    )
    assert response.status_code == 403


def test_logout_requires_csrf_header(client):
    register(client)
    response = client.post("/auth/logout", headers=auth_headers())
    assert response.status_code == 403
    assert client.get("/auth/me").status_code == 200


def test_logout_rejects_header_copied_from_another_value(client):
    registered = register(client)
    forged = "token-diferente-do-armazenado"
    client.cookies.set("leozera_csrf", forged)
    response = client.post("/auth/logout", headers=auth_headers(forged))
    assert response.status_code == 403
    assert "leozera_csrf" in registered.cookies


def test_logout_accepts_header_bound_to_session_even_if_cookie_changes(client):
    registered = register(client)
    csrf = registered.cookies["leozera_csrf"]
    client.cookies.set("leozera_csrf", "valor-substituido")
    response = client.post("/auth/logout", headers=auth_headers(csrf))
    assert response.status_code == 204


def test_get_me_does_not_require_csrf(client):
    register(client)
    assert client.get("/auth/me").status_code == 200


def test_session_cookie_is_httponly_and_csrf_cookie_is_not(client):
    response = register(client)
    raw_cookies = response.headers.get_list("set-cookie")
    session_cookie = next(item for item in raw_cookies if item.startswith("leozera_session="))
    csrf_cookie = next(item for item in raw_cookies if item.startswith("leozera_csrf="))
    assert "httponly" in session_cookie.lower()
    assert "httponly" not in csrf_cookie.lower()
    assert "samesite=lax" in session_cookie.lower()
    assert "samesite=lax" in csrf_cookie.lower()
