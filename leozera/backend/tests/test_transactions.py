from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.time import local_today
from app.main import app
from tests.conftest import TEST_DATABASE_URL
from tests.helpers import (
    balance_of,
    create_account,
    create_category,
    default_account,
    headers,
    open_account,
    post_entry,
    register,
)


def test_income_and_expense_change_balance_with_decimal_precision(client):
    _, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    today = local_today().isoformat()
    post_entry(client, csrf, account["id"], category["id"], "income", "0.10", today)
    post_entry(client, csrf, account["id"], category["id"], "income", "0.20", today)
    body = balance_of(client, account["id"])
    assert body["balance"] == "0.30"
    assert body["income_total"] == "0.30"
    assert isinstance(body["balance"], str)


def test_edit_moves_the_effect_between_accounts(client):
    _, csrf = register(client)
    cash = default_account(client)
    nubank = create_account(client, csrf, "Nubank")
    category = create_category(client, csrf)
    today = local_today().isoformat()
    entry = post_entry(client, csrf, cash["id"], category["id"], "expense", "100.00", today)
    edited = client.patch(
        f"/transactions/{entry['id']}",
        json={"amount": "150.00", "account_id": nubank["id"]},
        headers=headers(csrf),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["id"] == entry["id"]
    assert balance_of(client, cash["id"])["balance"] == "0.00"
    assert balance_of(client, nubank["id"])["balance"] == "-150.00"


def test_logical_delete_and_restore(client):
    _, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    today = local_today().isoformat()
    entry = post_entry(client, csrf, account["id"], category["id"], "income", "40.00", today)
    deleted = client.delete(f"/transactions/{entry['id']}", headers=headers(csrf))
    assert deleted.status_code == 200
    assert deleted.json()["deleted_at"] is not None
    assert balance_of(client, account["id"])["balance"] == "0.00"
    hidden = client.get("/transactions").json()["items"]
    assert hidden == []
    visible = client.get("/transactions?include_deleted=true").json()["items"]
    assert visible[0]["id"] == entry["id"]
    restored = client.post(f"/transactions/{entry['id']}/restore", headers=headers(csrf))
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert balance_of(client, account["id"])["balance"] == "40.00"


def test_retroactive_entry_and_future_date(client):
    _, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    open_account(client, csrf, account["id"], days=5)
    yesterday = (local_today() - timedelta(days=1)).isoformat()
    older = (local_today() - timedelta(days=4)).isoformat()
    post_entry(client, csrf, account["id"], category["id"], "income", "70.00", yesterday)
    assert balance_of(client, account["id"], older)["balance"] == "0.00"
    assert balance_of(client, account["id"], yesterday)["balance"] == "70.00"
    assert balance_of(client, account["id"])["balance"] == "70.00"
    future = client.post(
        "/transactions",
        json={
            "account_id": account["id"],
            "category_id": category["id"],
            "kind": "income",
            "amount": "1.00",
            "occurred_on": (local_today() + timedelta(days=1)).isoformat(),
        },
        headers=headers(csrf),
    )
    assert future.status_code == 422
    too_early = client.post(
        "/transactions",
        json={
            "account_id": account["id"],
            "category_id": category["id"],
            "kind": "income",
            "amount": "1.00",
            "occurred_on": (local_today() - timedelta(days=6)).isoformat(),
        },
        headers=headers(csrf),
    )
    assert too_early.status_code == 422


def test_transaction_filters_pagination_and_description(client):
    _, csrf = register(client)
    account = default_account(client)
    other = create_account(client, csrf, "Nubank")
    market = create_category(client, csrf, "Mercado")
    rent = create_category(client, csrf, "Aluguel")
    open_account(client, csrf, account["id"])
    open_account(client, csrf, other["id"])
    first = (local_today() - timedelta(days=3)).isoformat()
    second = (local_today() - timedelta(days=2)).isoformat()
    third = (local_today() - timedelta(days=1)).isoformat()
    post_entry(client, csrf, account["id"], market["id"], "expense", "10.00", first, "feira")
    post_entry(client, csrf, account["id"], rent["id"], "expense", "20.00", second, "Aluguel do mes")
    post_entry(client, csrf, other["id"], market["id"], "income", "30.00", third, "salario")
    page = client.get("/transactions?limit=2&order=asc")
    assert page.status_code == 200
    body = page.json()
    assert [item["occurred_on"] for item in body["items"]] == [first, second]
    assert body["next_cursor"]
    next_page = client.get(f"/transactions?limit=2&order=asc&cursor={body['next_cursor']}")
    assert [item["occurred_on"] for item in next_page.json()["items"]] == [third]
    assert next_page.json()["next_cursor"] is None
    by_account = client.get(f"/transactions?account_id={other['id']}").json()["items"]
    assert len(by_account) == 1
    assert by_account[0]["effect"] == "30.00"
    by_category = client.get(f"/transactions?category_id={rent['id']}").json()["items"]
    assert len(by_category) == 1
    by_kind = client.get("/transactions?kind=income").json()["items"]
    assert len(by_kind) == 1
    by_text = client.get("/transactions?description=aluguel").json()["items"]
    assert len(by_text) == 1
    escaped = client.get("/transactions?description=100%").json()["items"]
    assert escaped == []
    ranged = client.get(f"/transactions?occurred_from={second}&occurred_to={second}").json()["items"]
    assert len(ranged) == 1


def test_excess_scale_and_float_are_rejected(client):
    _, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    rejected = client.post(
        "/transactions",
        json={
            "account_id": account["id"],
            "category_id": category["id"],
            "kind": "income",
            "amount": "1.115",
            "occurred_on": local_today().isoformat(),
        },
        headers=headers(csrf),
    )
    assert rejected.status_code == 422
    floating = client.post(
        "/transactions",
        json={
            "account_id": account["id"],
            "category_id": category["id"],
            "kind": "income",
            "amount": 0.1,
            "occurred_on": local_today().isoformat(),
        },
        headers=headers(csrf),
    )
    assert floating.status_code == 422


def test_changes_are_audited(client):
    _, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    entry = post_entry(
        client,
        csrf,
        account["id"],
        category["id"],
        "expense",
        "12.00",
        local_today().isoformat(),
        "padaria",
    )
    edited = client.patch(
        f"/transactions/{entry['id']}",
        json={"amount": "14.00"},
        headers=headers(csrf),
    )
    assert edited.status_code == 200
    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as connection:
        operations = connection.execute(
            text(
                """
                SELECT operation, before_data->>'amount', after_data->>'amount'
                FROM financial_audit_logs
                WHERE entity_id = :id
                ORDER BY created_at
                """
            ),
            {"id": entry["id"]},
        ).all()
    engine.dispose()
    assert operations[0][0] == "create"
    assert operations[0][1] is None
    assert operations[0][2] == "12.00"
    assert operations[1][0] == "update"
    assert operations[1][1] == "12.00"
    assert operations[1][2] == "14.00"


def test_commit_failure_rolls_back_entry_and_audit(client, monkeypatch, caplog):
    register(client)
    account = default_account(client)
    csrf = client.cookies["leozera_csrf"]
    category = create_category(client, csrf)
    today = local_today().isoformat()
    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as connection:
        before_entries = connection.execute(text("SELECT COUNT(*) FROM financial_entries")).scalar()
        before_audits = connection.execute(text("SELECT COUNT(*) FROM financial_audit_logs")).scalar()

    def fail_commit(self):
        raise RuntimeError("falha de commit")

    monkeypatch.setattr(Session, "commit", fail_commit)
    # O ServerErrorMiddleware envia o JSON 500 e relança a exceção. O TestClient,
    # por padrão, propaga esse relançamento; este cliente observa a resposta HTTP.
    with TestClient(app, raise_server_exceptions=False, cookies=client.cookies) as observer:
        response = observer.post(
            "/transactions",
            json={
                "account_id": account["id"],
                "category_id": category["id"],
                "kind": "income",
                "amount": "9.00",
                "occurred_on": today,
            },
            headers=headers(csrf),
        )
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Erro interno."}
    assert "falha de commit" not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text
    assert any(
        record.name == "leozera" and record.exc_info is not None and "falha de commit" in str(record.exc_info[1])
        for record in caplog.records
    )
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM financial_entries")).scalar() == before_entries
        assert connection.execute(text("SELECT COUNT(*) FROM financial_audit_logs")).scalar() == before_audits
    engine.dispose()

    monkeypatch.undo()
    accounts = client.get("/accounts")
    assert accounts.status_code == 200
    assert any(item["id"] == account["id"] for item in accounts.json())
    created = post_entry(client, csrf, account["id"], category["id"], "income", "1.00", today)
    assert created["amount"] == "1.00"
    rejected = client.post(
        "/transactions",
        json={
            "account_id": account["id"],
            "category_id": category["id"],
            "kind": "income",
            "amount": "9.00",
            "occurred_on": "2999-01-01",
        },
        headers=headers(csrf),
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "Não é permitido lançamento em data futura."


def test_audit_log_rejects_update_and_delete(client):
    register(client)
    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(Exception, match="imutavel"):
            connection.execute(text("UPDATE financial_audit_logs SET operation = 'create'"))
        transaction.rollback()
    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(Exception, match="imutavel"):
            connection.execute(text("DELETE FROM financial_audit_logs"))
        transaction.rollback()
    engine.dispose()
