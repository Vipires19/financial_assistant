import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select, text

from app.db.session import SessionLocal
from app.db.time import local_today
from app.models.financial_audit import FinancialAuditLog
from app.models.financial_entry import FinancialEntry
from app.models.user import User
from app.schemas.finance import AdjustmentCreate
from app.services.finance_service import create_adjustment
from tests.helpers import (
    AccountLock,
    balance_of,
    create_category,
    default_account,
    headers,
    open_account,
    post_entry,
    register,
    start_thread,
)


def test_positive_and_negative_adjustments_do_not_change_income_or_expense(client):
    _, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    today = local_today().isoformat()
    post_entry(client, csrf, account["id"], category["id"], "income", "100.00", today)
    positive = client.post(
        f"/accounts/{account['id']}/adjustments",
        json={"balance": "140.00", "occurred_on": today},
        headers=headers(csrf),
    )
    assert positive.status_code == 201, positive.text
    assert positive.json()["kind"] == "adjustment"
    assert positive.json()["amount"] == "40.00"
    assert positive.json()["category_name"] == "Ajuste de saldo"
    body = balance_of(client, account["id"])
    assert body["balance"] == "140.00"
    assert body["income_total"] == "100.00"
    assert body["expense_total"] == "0.00"
    negative = client.post(
        f"/accounts/{account['id']}/adjustments",
        json={"balance": "40.00", "occurred_on": today, "description": "conferencia"},
        headers=headers(csrf),
    )
    assert negative.status_code == 201, negative.text
    assert negative.json()["amount"] == "-100.00"
    body = balance_of(client, account["id"])
    assert body["balance"] == "40.00"
    assert body["income_total"] == "100.00"
    assert body["expense_total"] == "0.00"


def test_zero_difference_does_not_create_an_adjustment(client):
    _, csrf = register(client)
    account = default_account(client)
    before = _audit_count()
    response = client.post(
        f"/accounts/{account['id']}/adjustments",
        json={"balance": "0.00", "occurred_on": local_today().isoformat()},
        headers=headers(csrf),
    )
    assert response.status_code == 422
    assert client.get("/transactions?kind=adjustment").json()["items"] == []
    assert _audit_count() == before


def test_retroactive_adjustment_uses_the_balance_on_that_date(client):
    _, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    open_account(client, csrf, account["id"], days=10)
    yesterday = (local_today() - timedelta(days=1)).isoformat()
    today = local_today().isoformat()
    post_entry(client, csrf, account["id"], category["id"], "income", "100.00", today)
    assert balance_of(client, account["id"], yesterday)["balance"] == "0.00"
    created = client.post(
        f"/accounts/{account['id']}/adjustments",
        json={"balance": "25.00", "occurred_on": yesterday},
        headers=headers(csrf),
    )
    assert created.status_code == 201, created.text
    assert created.json()["amount"] == "25.00"
    assert balance_of(client, account["id"], yesterday)["balance"] == "25.00"
    assert balance_of(client, account["id"])["balance"] == "125.00"
    assert balance_of(client, account["id"])["income_total"] == "100.00"


def test_adjustment_delta_stays_when_later_entries_change(client):
    """O delta gravado não é reescrito quando outro lançamento muda depois."""

    _, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    open_account(client, csrf, account["id"], days=10)
    yesterday = (local_today() - timedelta(days=1)).isoformat()
    today = local_today().isoformat()
    income = post_entry(client, csrf, account["id"], category["id"], "income", "100.00", today)
    created = client.post(
        f"/accounts/{account['id']}/adjustments",
        json={"balance": "25.00", "occurred_on": yesterday},
        headers=headers(csrf),
    )
    adjustment_id = created.json()["id"]
    edited = client.patch(
        f"/transactions/{income['id']}",
        json={"amount": "80.00"},
        headers=headers(csrf),
    )
    assert edited.status_code == 200
    stored = client.get(f"/transactions/{adjustment_id}").json()
    assert stored["amount"] == "25.00"
    assert balance_of(client, account["id"], yesterday)["balance"] == "25.00"
    assert balance_of(client, account["id"])["balance"] == "105.00"


def test_same_day_entries_have_no_intraday_order_and_do_not_rewrite_adjustment(client):
    """Lançamentos do mesmo DATE entram juntos. Um lançamento posterior não reordena o ajuste."""

    _, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    open_account(client, csrf, account["id"], days=10)
    day = (local_today() - timedelta(days=1)).isoformat()
    income = post_entry(client, csrf, account["id"], category["id"], "income", "30.00", day)
    post_entry(client, csrf, account["id"], category["id"], "expense", "10.00", day)
    created = client.post(
        f"/accounts/{account['id']}/adjustments",
        json={"balance": "100.00", "occurred_on": day},
        headers=headers(csrf),
    )
    assert created.status_code == 201, created.text
    assert created.json()["amount"] == "80.00"
    post_entry(client, csrf, account["id"], category["id"], "income", "5.00", day)
    client.patch(f"/transactions/{income['id']}", json={"amount": "40.00"}, headers=headers(csrf))
    stored = client.get(f"/transactions/{created.json()['id']}").json()
    assert stored["amount"] == "80.00"
    assert balance_of(client, account["id"], day)["balance"] == "115.00"


def test_adjustment_edit_keeps_the_id_and_delete_restores_balance(client):
    _, csrf = register(client)
    account = default_account(client)
    today = local_today().isoformat()
    created = client.post(
        f"/accounts/{account['id']}/adjustments",
        json={"balance": "30.00", "occurred_on": today},
        headers=headers(csrf),
    )
    adjustment_id = created.json()["id"]
    edited = client.patch(
        f"/accounts/{account['id']}/adjustments/{adjustment_id}",
        json={"balance": "12.50"},
        headers=headers(csrf),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["id"] == adjustment_id
    assert edited.json()["amount"] == "12.50"
    assert balance_of(client, account["id"])["balance"] == "12.50"
    removed = client.delete(
        f"/accounts/{account['id']}/adjustments/{adjustment_id}",
        headers=headers(csrf),
    )
    assert removed.status_code == 200
    assert balance_of(client, account["id"])["balance"] == "0.00"
    restored = client.post(
        f"/accounts/{account['id']}/adjustments/{adjustment_id}/restore",
        headers=headers(csrf),
    )
    assert restored.status_code == 200
    assert balance_of(client, account["id"])["balance"] == "12.50"
    ordinary = client.patch(
        f"/transactions/{adjustment_id}",
        json={"amount": "1.00"},
        headers=headers(csrf),
    )
    assert ordinary.status_code == 409
    scaled = client.post(
        f"/accounts/{account['id']}/adjustments",
        json={"balance": "1.115", "occurred_on": today},
        headers=headers(csrf),
    )
    assert scaled.status_code == 422


def test_concurrent_adjustment_uses_the_balance_committed_by_the_lock_holder(client):
    user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    account_id = uuid.UUID(account["id"])
    user_id = uuid.UUID(user["id"])
    holder = AccountLock(account_id)

    def worker():
        db = SessionLocal()
        try:
            db.execute(text("SET lock_timeout = '8s'"))
            current = db.get(User, user_id)
            return create_adjustment(
                db,
                current,
                account_id,
                AdjustmentCreate(balance=Decimal("150.00"), occurred_on=local_today()),
            )
        finally:
            db.close()

    try:
        holder.acquire()
        thread, box = start_thread(worker)
        holder.wait_for_waiter(box)
        holder.execute(
            """
            INSERT INTO financial_entries (
                id, user_id, kind, account_id, category_id, amount, occurred_on
            ) VALUES (
                :id, :user_id, 'income', :account_id, :category_id, 100.00, :occurred_on
            )
            """,
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "account_id": account_id,
                "category_id": category["id"],
                "occurred_on": local_today(),
            },
        )
        holder.release()
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert "error" not in box, box.get("error")
        assert box["value"].amount == "50.00"
    finally:
        holder.close()
    body = balance_of(client, account["id"])
    assert body["balance"] == "150.00"
    assert body["income_total"] == "100.00"
    assert body["expense_total"] == "0.00"


def _audit_count() -> tuple[int, int]:
    db = SessionLocal()
    try:
        entries = db.scalar(select(func.count()).select_from(FinancialEntry))
        audits = db.scalar(
            select(func.count())
            .select_from(FinancialAuditLog)
            .where(FinancialAuditLog.entity_type == "financial_entry")
        )
        return entries, audits
    finally:
        db.close()
