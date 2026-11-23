import uuid

from fastapi.testclient import TestClient

from app.db.time import local_today
from app.main import app
from tests.helpers import create_account, create_category, default_account, headers, register
from tests.test_auth import USER


def test_user_cannot_read_or_change_another_users_finances(client):
    _, csrf_a = register(client)
    account_a = default_account(client)
    category_a = create_category(client, csrf_a, "Mercado")
    other = create_account(client, csrf_a, "Nubank")
    transfer = client.post(
        "/transfers",
        json={
            "from_account_id": account_a["id"],
            "to_account_id": other["id"],
            "amount": "5.00",
            "occurred_on": local_today().isoformat(),
        },
        headers=headers(csrf_a),
    )
    assert transfer.status_code == 201, transfer.text

    with TestClient(app) as second:
        _, csrf_b = register(second, name="Bia", email="bia@example.com", password="senha-segura-2")
        account_b = default_account(second)
        assert account_b["id"] != account_a["id"]
        assert second.get(f"/accounts/{account_a['id']}").status_code == 404
        assert (
            second.patch(
                f"/categories/{category_a['id']}",
                json={"name": "Invadida"},
                headers=headers(csrf_b),
            ).status_code
            == 404
        )
        assert (
            second.post(
                "/transactions",
                json={
                    "account_id": account_a["id"],
                    "category_id": category_a["id"],
                    "kind": "expense",
                    "amount": "1.00",
                    "occurred_on": local_today().isoformat(),
                },
                headers=headers(csrf_b),
            ).status_code
            == 404
        )
        assert (
            second.patch(
                f"/transfers/{transfer.json()['id']}",
                json={"amount": "9.00"},
                headers=headers(csrf_b),
            ).status_code
            == 404
        )
        assert second.get(f"/transactions/{transfer.json()['id']}").status_code == 404
        assert client.get(f"/accounts/{account_a['id']}").status_code == 200
        renamed = client.get("/categories")
        assert any(item["name"] == "Mercado" for item in renamed.json())


def test_financial_endpoints_require_authentication(client):
    assert client.get("/accounts").status_code == 401
    assert client.get("/categories").status_code == 401
    assert client.get("/transactions").status_code == 401
    assert client.get(f"/accounts/{uuid.uuid4()}/balance").status_code == 401
    assert client.post(
        "/accounts",
        json={"name": "Carteira"},
        headers={"Origin": "http://localhost:3000"},
    ).status_code == 401


def test_financial_writes_reject_invalid_csrf(client):
    register(client)
    missing = client.post(
        "/accounts",
        json={"name": "Carteira"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert missing.status_code == 403
    forged = client.post(
        "/transactions",
        json={
            "account_id": str(uuid.uuid4()),
            "category_id": str(uuid.uuid4()),
            "kind": "expense",
            "amount": "1.00",
            "occurred_on": local_today().isoformat(),
        },
        headers=headers("token-forjado"),
    )
    assert forged.status_code == 403
    assert client.get("/accounts").status_code == 200


def test_register_payload_from_phase_one_still_authenticates(client):
    response = client.post("/auth/register", json=USER, headers=headers("ignorado"))
    assert response.status_code == 201
    assert response.json()["email"] == USER["email"]
