from datetime import timedelta

from app.db.time import local_today
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


def test_summary_requires_authentication(client):
    response = client.get("/summary")
    assert response.status_code == 401


def test_new_user_summary_is_zero_for_the_current_month(client):
    register(client)
    today = local_today()
    response = client.get("/summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["as_of"] == today.isoformat()
    assert body["period_from"] == today.replace(day=1).isoformat()
    assert body["period_to"] == today.isoformat()
    assert body["total_balance"] == "0.00"
    assert body["period_income"] == "0.00"
    assert body["period_expense"] == "0.00"
    assert body["period_result"] == "0.00"


def test_summary_uses_period_income_and_expense_only(client):
    _, csrf = register(client)
    cash = default_account(client)
    other = create_account(client, csrf, "Nubank", initial="15.00")
    open_account(client, csrf, cash["id"], days=40)
    open_account(client, csrf, other["id"], days=40)
    category = create_category(client, csrf)
    today = local_today()
    previous = (today.replace(day=1) - timedelta(days=1)).isoformat()
    post_entry(client, csrf, cash["id"], category["id"], "income", "10.00", previous)
    post_entry(client, csrf, cash["id"], category["id"], "income", "4.00", today.isoformat())
    post_entry(client, csrf, cash["id"], category["id"], "expense", "1.50", today.isoformat())
    removed = post_entry(client, csrf, cash["id"], category["id"], "income", "9.00", today.isoformat())
    deleted = client.delete(f"/transactions/{removed['id']}", headers=headers(csrf))
    assert deleted.status_code == 200, deleted.text
    transferred = client.post(
        "/transfers",
        json={
            "from_account_id": cash["id"],
            "to_account_id": other["id"],
            "amount": "2.00",
            "occurred_on": today.isoformat(),
        },
        headers=headers(csrf),
    )
    assert transferred.status_code == 201, transferred.text

    response = client.get("/summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["period_income"] == "4.00"
    assert body["period_expense"] == "1.50"
    assert body["period_result"] == "2.50"
    cash_balance = balance_of(client, cash["id"])["balance"]
    other_balance = balance_of(client, other["id"])["balance"]
    assert body["total_balance"] == _sum_money(cash_balance, other_balance)

    previous_only = client.get("/summary", params={"occurred_from": previous, "occurred_to": previous})
    assert previous_only.status_code == 200, previous_only.text
    assert previous_only.json()["period_income"] == "10.00"
    assert previous_only.json()["period_expense"] == "0.00"
    assert previous_only.json()["period_result"] == "10.00"


def test_adjustment_and_archived_account_stay_in_the_balance_only(client):
    _, csrf = register(client)
    cash = default_account(client)
    saved = create_account(client, csrf, "Poupança", initial="30.00")
    archived = client.post(f"/accounts/{saved['id']}/archive", headers=headers(csrf))
    assert archived.status_code == 200, archived.text
    adjusted = client.post(
        f"/accounts/{cash['id']}/adjustments",
        json={"balance": "80.00", "occurred_on": local_today().isoformat()},
        headers=headers(csrf),
    )
    assert adjusted.status_code == 201, adjusted.text

    body = client.get("/summary").json()
    assert body["total_balance"] == "110.00"
    assert body["period_income"] == "0.00"
    assert body["period_expense"] == "0.00"
    assert body["period_result"] == "0.00"


def test_summary_rejects_inverted_period(client):
    register(client)
    response = client.get("/summary", params={"occurred_from": "2026-11-16", "occurred_to": "2026-11-01"})
    assert response.status_code == 422
    assert response.json()["detail"] == "A data inicial não pode ser posterior à data final."


def _sum_money(left: str, right: str) -> str:
    from decimal import Decimal

    from app.schemas.finance import format_money

    return format_money(Decimal(left) + Decimal(right))
