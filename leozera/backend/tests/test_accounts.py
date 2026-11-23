import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import create_engine, select, text

from app.db.session import SessionLocal
from app.db.time import local_today
from app.models.category import Category
from app.models.financial_account import FinancialAccount
from app.models.financial_audit import FinancialAuditLog
from app.models.user import User
from app.schemas.finance import AccountUpdate
from app.services.finance_service import FinanceError, provision_user_finance, update_account
from tests.conftest import TEST_DATABASE_URL
from tests.helpers import (
    AccountLock,
    balance_of,
    create_account,
    create_category,
    default_account,
    headers,
    open_account,
    post_entry,
    register,
    start_thread,
)


def test_register_creates_cash_account_with_zero_balance(client):
    register(client)
    account = default_account(client)
    assert account["name"] == "Dinheiro"
    assert account["initial_balance"] == "0.00"
    assert account["is_default"] is True
    assert account["balance"] == "0.00"
    assert account["opened_on"] == local_today().isoformat()
    categories = client.get("/categories").json()
    internal = next(item for item in categories if item["is_internal"])
    assert internal["name"] == "Ajuste de saldo"
    assert internal["code"] == "balance_adjustment"


def test_provision_is_idempotent_for_existing_user():
    db = SessionLocal()
    try:
        user = User(name="Cris", email="cris@example.com", hashed_password="hash")
        db.add(user)
        db.flush()
        provision_user_finance(db, user)
        user_id = user.id
        account = db.scalar(select(FinancialAccount).where(FinancialAccount.user_id == user_id))
        account.name = "Carteira"
        provision_user_finance(db, user)
        db.commit()
        accounts = list(db.scalars(select(FinancialAccount).where(FinancialAccount.user_id == user_id)))
        categories = list(db.scalars(select(Category).where(Category.user_id == user_id)))
        assert len(accounts) == 1
        assert accounts[0].name == "Carteira"
        assert accounts[0].initial_balance == Decimal("0.00")
        assert accounts[0].is_default is True
        assert len(categories) == 1
        assert categories[0].is_internal is True
    finally:
        db.close()


def test_negative_balance_does_not_block_another_expense(client):
    _, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    post_entry(client, csrf, account["id"], category["id"], "expense", "25.00", local_today().isoformat())
    post_entry(client, csrf, account["id"], category["id"], "expense", "1.00", local_today().isoformat())
    body = balance_of(client, account["id"])
    assert body["balance"] == "-26.00"
    assert body["expense_total"] == "26.00"
    assert body["income_total"] == "0.00"


def test_initial_balance_is_not_income(client):
    _, csrf = register(client)
    account = create_account(client, csrf, name="Carteira", initial="0.10")
    body = balance_of(client, account["id"])
    assert body["balance"] == "0.10"
    assert body["income_total"] == "0.00"


def test_archive_preserves_history_and_blocks_new_entries(client):
    _, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    today = local_today().isoformat()
    entry = post_entry(client, csrf, account["id"], category["id"], "expense", "10.00", today)
    archived = client.post(f"/accounts/{account['id']}/archive", headers=headers(csrf))
    assert archived.status_code == 200
    assert client.get("/accounts").json() == []
    listed = client.get("/accounts?include_archived=true")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == account["id"]
    assert balance_of(client, account["id"])["balance"] == "-10.00"
    rejected = post_entry_raw(client, csrf, account["id"], category["id"], "expense", "1.00", today)
    assert rejected.status_code == 422
    edited = client.patch(
        f"/transactions/{entry['id']}",
        json={"amount": "15.00"},
        headers=headers(csrf),
    )
    assert edited.status_code == 200, edited.text
    assert balance_of(client, account["id"])["balance"] == "-15.00"
    restored = client.post(f"/accounts/{account['id']}/reactivate", headers=headers(csrf))
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None


def post_entry_raw(client, csrf, account_id, category_id, kind, amount, occurred_on):
    return client.post(
        "/transactions",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "kind": kind,
            "amount": amount,
            "occurred_on": occurred_on,
        },
        headers=headers(csrf),
    )


def test_control_start_revision_preserves_initial_balance_meaning(client):
    _, csrf = register(client)
    account = default_account(client)
    future = (local_today() + timedelta(days=1)).isoformat()
    rejected = client.patch(
        f"/accounts/{account['id']}",
        json={"opened_on": future},
        headers=headers(csrf),
    )
    assert rejected.status_code == 422
    opened = open_account(client, csrf, account["id"], days=10)
    category = create_category(client, csrf)
    yesterday = (local_today() - timedelta(days=1)).isoformat()
    post_entry(client, csrf, account["id"], category["id"], "income", "20.00", yesterday)
    moved = client.patch(
        f"/accounts/{account['id']}",
        json={"opened_on": local_today().isoformat()},
        headers=headers(csrf),
    )
    assert moved.status_code == 422
    earlier = client.patch(
        f"/accounts/{account['id']}",
        json={"opened_on": opened, "initial_balance": "5.00"},
        headers=headers(csrf),
    )
    assert earlier.status_code == 200, earlier.text
    body = balance_of(client, account["id"])
    assert body["balance"] == "25.00"
    assert body["income_total"] == "20.00"


def test_money_scale_is_rejected_before_persistence(client):
    _, csrf = register(client)
    rejected = client.post(
        "/accounts",
        json={"name": "Carteira", "initial_balance": "1.115"},
        headers=headers(csrf),
    )
    assert rejected.status_code == 422
    account = default_account(client)
    patched = client.patch(
        f"/accounts/{account['id']}",
        json={"initial_balance": "1.115"},
        headers=headers(csrf),
    )
    assert patched.status_code == 422
    floating = client.post(
        "/accounts",
        json={"name": "Outra", "initial_balance": 10.1},
        headers=headers(csrf),
    )
    assert floating.status_code == 422
    accepted = client.post(
        "/accounts",
        json={"name": "Carteira", "initial_balance": "1.2300"},
        headers=headers(csrf),
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["initial_balance"] == "1.23"
    assert client.get(f"/accounts/{account['id']}").json()["initial_balance"] == "0.00"


def test_postgres_numeric_column_rounds_excess_scale(client):
    """NUMERIC(19,2) arredonda no banco. A API precisa recusar antes do INSERT."""

    register(client)
    account = default_account(client)
    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as connection:
        transaction = connection.begin()
        stored = connection.execute(
            text(
                """
                UPDATE financial_accounts
                SET initial_balance = '1.115'
                WHERE id = :id
                RETURNING initial_balance
                """
            ),
            {"id": account["id"]},
        ).scalar()
        negative = connection.execute(text("SELECT CAST('-0.005' AS NUMERIC(19,2))")).scalar()
        transaction.rollback()
    engine.dispose()
    assert stored == Decimal("1.12")
    assert negative == Decimal("-0.01")
    assert client.get(f"/accounts/{account['id']}").json()["initial_balance"] == "0.00"


def test_concurrent_initial_balance_waits_and_reads_the_locked_row(client):
    user, csrf = register(client)
    account = default_account(client)
    account_id = uuid.UUID(account["id"])
    user_id = uuid.UUID(user["id"])
    holder = AccountLock(account_id)

    def worker():
        db = SessionLocal()
        try:
            db.execute(text("SET lock_timeout = '8s'"))
            current = db.get(User, user_id)
            return update_account(
                db,
                current,
                account_id,
                AccountUpdate(initial_balance=Decimal("50.00")),
            )
        finally:
            db.close()

    try:
        holder.acquire()
        thread, box = start_thread(worker)
        holder.wait_for_waiter(box)
        holder.execute(
            "UPDATE financial_accounts SET initial_balance = 80.00 WHERE id = :id",
            {"id": account_id},
        )
        holder.release()
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert "error" not in box, box.get("error")
        assert box["value"].initial_balance == "50.00"
    finally:
        holder.close()

    db = SessionLocal()
    try:
        log = db.scalar(
            select(FinancialAuditLog)
            .where(
                FinancialAuditLog.entity_id == account_id,
                FinancialAuditLog.operation == "update",
            )
            .order_by(FinancialAuditLog.created_at.desc())
        )
        assert log.before_data["initial_balance"] == "80.00"
        assert log.after_data["initial_balance"] == "50.00"
    finally:
        db.close()


def test_concurrent_archive_blocks_a_new_entry(client):
    user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    account_id = uuid.UUID(account["id"])
    user_id = uuid.UUID(user["id"])
    holder = AccountLock(account_id)

    def worker():
        from app.schemas.finance import TransactionCreate

        from app.services.finance_service import create_transaction

        db = SessionLocal()
        try:
            db.execute(text("SET lock_timeout = '8s'"))
            current = db.get(User, user_id)
            return create_transaction(
                db,
                current,
                TransactionCreate(
                    account_id=account_id,
                    category_id=uuid.UUID(category["id"]),
                    kind="expense",
                    amount=Decimal("10.00"),
                    occurred_on=local_today(),
                ),
            )
        finally:
            db.close()

    try:
        holder.acquire()
        thread, box = start_thread(worker)
        holder.wait_for_waiter(box)
        holder.execute(
            "UPDATE financial_accounts SET archived_at = CURRENT_TIMESTAMP WHERE id = :id",
            {"id": account_id},
        )
        holder.release()
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert isinstance(box["error"], FinanceError)
        assert box["error"].status_code == 422
    finally:
        holder.close()
    listed = client.get("/transactions")
    assert listed.json()["items"] == []


def test_concurrent_opening_date_sees_entry_inserted_while_waiting(client):
    user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    open_account(client, csrf, account["id"], days=10)
    account_id = uuid.UUID(account["id"])
    user_id = uuid.UUID(user["id"])
    yesterday = local_today() - timedelta(days=1)
    holder = AccountLock(account_id)

    def worker():
        db = SessionLocal()
        try:
            db.execute(text("SET lock_timeout = '8s'"))
            current = db.get(User, user_id)
            return update_account(
                db,
                current,
                account_id,
                AccountUpdate(opened_on=local_today()),
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
                :id, :user_id, 'income', :account_id, :category_id, 10.00, :occurred_on
            )
            """,
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "account_id": account_id,
                "category_id": category["id"],
                "occurred_on": yesterday,
            },
        )
        holder.release()
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert isinstance(box["error"], FinanceError)
        assert box["error"].status_code == 422
    finally:
        holder.close()
    current = client.get(f"/accounts/{account['id']}").json()
    assert current["opened_on"] == (local_today() - timedelta(days=10)).isoformat()


def test_balance_before_control_start_is_rejected(client):
    _, csrf = register(client)
    account = default_account(client)
    yesterday = (local_today() - timedelta(days=1)).isoformat()
    response = client.get(f"/accounts/{account['id']}/balance?on={yesterday}")
    assert response.status_code == 422
