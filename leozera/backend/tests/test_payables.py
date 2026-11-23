import time
import uuid
from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.main import app

from app.db.session import SessionLocal
from app.db.time import local_today
from app.models.financial_audit import FinancialAuditLog
from app.models.financial_entry import FinancialEntry
from app.models.payable import PayableSettlement
from app.models.user import User
from app.schemas.finance import TransactionCreate, TransactionUpdate
from app.schemas.payable import PaymentCreate
from app.services.finance_service import (
    FinanceError,
    create_transaction,
    delete_transaction,
    restore_transaction,
    update_transaction,
)
from app.services.payable_service import SettlementDraft, pay_obligation, settle_obligations
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


def _assert_accounts_locked_before_obligation(observer) -> None:
    deadline = time.monotonic() + 8
    activity = text(
        """
        SELECT a.pid, a.state, a.query,
               EXISTS (
                   SELECT 1
                   FROM pg_locks
                   WHERE pid = a.pid
                     AND granted
                     AND mode = 'RowShareLock'
                     AND relation = 'financial_accounts'::regclass
               ) AS account_locked,
               EXISTS (
                   SELECT 1
                   FROM pg_locks
                   WHERE pid = a.pid
                     AND granted
                     AND mode = 'RowShareLock'
                     AND relation = 'payable_obligations'::regclass
               ) AS obligation_locked
        FROM pg_stat_activity a
        WHERE a.datname = current_database()
          AND a.pid <> pg_backend_pid()
          AND a.wait_event_type = 'Lock'
        """
    )
    while time.monotonic() < deadline:
        rows = observer.execute(activity).all()
        for row in rows:
            query = row.query or ""
            waiting_for_account = row.state == "active" and "financial_accounts" in query
            if waiting_for_account and row.obligation_locked:
                raise AssertionError(f"A conta foi esperada depois da obrigação. query={query}")
            if row.account_locked and (row.obligation_locked or "payable_obligations" in query):
                return
        time.sleep(0.05)
    raise AssertionError("A operação não segurou a conta antes de esperar a obrigação.")


def pay(client, csrf, obligation_id, account_id, *, amount=None, category_id=None, occurred_on=None, key="pagamento-1"):
    payload = {"account_id": account_id}
    if amount is not None:
        payload["amount"] = amount
    if category_id is not None:
        payload["category_id"] = category_id
    if occurred_on is not None:
        payload["occurred_on"] = occurred_on
    return client.post(
        f"/payables/{obligation_id}/payments",
        json=payload,
        headers={**headers(csrf), "Idempotency-Key": key},
    )


def create_payable(client, csrf, *, description="Internet", amount="120.00", due_on=None, category_id=None):
    payload = {
        "description": description,
        "expected_amount": amount,
        "due_on": (due_on or local_today()).isoformat(),
    }
    if category_id is not None:
        payload["category_id"] = category_id
    response = client.post("/payables", json=payload, headers=headers(csrf))
    assert response.status_code == 201, response.text
    return response.json()


def test_creates_obligation_without_an_account_and_without_touching_balance(client):
    _user, csrf = register(client)
    account = default_account(client)
    before = client.get("/summary").json()
    created = create_payable(client, csrf, due_on=local_today() - timedelta(days=1))
    assert created["status"] == "overdue"
    assert created["expected_amount"] == "120.00"
    assert created["settlements"] == []
    assert "account_id" not in created
    assert client.get("/summary").json() == before
    assert balance_of(client, account["id"])["balance"] == account["balance"]


def test_payable_summary_totals_are_global(client):
    _user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    today = local_today()
    assert client.get("/payables/summary").json() == {
        "open_expected": "0.00",
        "overdue_expected": "0.00",
        "paid_amount": "0.00",
    }
    create_payable(client, csrf, description="Aberta", amount="100.00", due_on=today, category_id=category["id"])
    create_payable(
        client,
        csrf,
        description="Vencida",
        amount="40.00",
        due_on=today - timedelta(days=1),
        category_id=category["id"],
    )
    paid = create_payable(client, csrf, description="Paga", amount="80.00", due_on=today, category_id=category["id"])
    payment = pay(client, csrf, paid["id"], account["id"], amount="55.00", key="resumo-pago")
    assert payment.status_code == 201, payment.text
    archived = create_payable(client, csrf, description="Arquivada", amount="999.00", category_id=category["id"])
    assert client.post(f"/payables/{archived['id']}/archive", headers=headers(csrf)).status_code == 200
    released = create_payable(client, csrf, description="Liberada", amount="30.00", due_on=today, category_id=category["id"])
    released_payment = pay(client, csrf, released["id"], account["id"], key="resumo-liberada")
    assert released_payment.status_code == 201, released_payment.text
    assert client.delete(
        f"/transactions/{released_payment.json()['entry_id']}",
        headers=headers(csrf),
    ).status_code == 200
    expected = {
        "open_expected": "130.00",
        "overdue_expected": "40.00",
        "paid_amount": "55.00",
    }
    assert client.get("/payables/summary").json() == expected
    page = client.get("/payables?limit=1").json()
    assert len(page["items"]) == 1
    assert client.get("/payables/summary").json() == expected
    movements = client.get("/transactions").json()["items"]
    assert [item["amount"] for item in movements] == ["55.00"]
    assert movements[0]["kind"] == "expense"
    assert client.get("/summary").json()["period_expense"] == "55.00"


def test_rejects_invalid_money_and_internal_category(client):
    _user, csrf = register(client)
    due = local_today().isoformat()
    floated = client.post(
        "/payables",
        json={"description": "Internet", "expected_amount": 10.5, "due_on": due},
        headers=headers(csrf),
    )
    assert floated.status_code == 422
    precise = client.post(
        "/payables",
        json={"description": "Internet", "expected_amount": "10.555", "due_on": due},
        headers=headers(csrf),
    )
    assert precise.status_code == 422
    internal = next(item for item in client.get("/categories").json() if item["is_internal"])
    rejected = client.post(
        "/payables",
        json={
            "description": "Internet",
            "expected_amount": "10.00",
            "due_on": due,
            "category_id": internal["id"],
        },
        headers=headers(csrf),
    )
    assert rejected.status_code == 422


def test_isolates_obligations_and_payment_accounts(client):
    _user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf, name="Casa")
    own = create_payable(client, csrf, category_id=category["id"])
    with TestClient(app) as second:
        _other, other_csrf = register(second, name="Bruno", email="bruno@example.com")
        foreign_account = default_account(second)
        foreign_category = create_category(second, other_csrf, name="Casa")
        assert second.get(f"/payables/{own['id']}").status_code == 404
        leaked = pay(
            second,
            other_csrf,
            own["id"],
            foreign_account["id"],
            category_id=foreign_category["id"],
            key="isolamento-1",
        )
        assert leaked.status_code == 404
        foreign_payment = pay(
            client,
            csrf,
            own["id"],
            foreign_account["id"],
            key="isolamento-2",
        )
        assert foreign_payment.status_code == 404
    paid = pay(client, csrf, own["id"], account["id"], key="isolamento-3")
    assert paid.status_code == 201, paid.text


def test_payment_creates_one_expense_and_uses_default_or_override_category(client):
    _user, csrf = register(client)
    account = default_account(client)
    salary = create_category(client, csrf, name="Salário")
    market = create_category(client, csrf, name="Mercado")
    obligation = create_payable(client, csrf, category_id=salary["id"], amount="200.00")
    paid = pay(client, csrf, obligation["id"], account["id"], amount="180.00", key="pago-1")
    assert paid.status_code == 201, paid.text
    body = paid.json()
    assert body["replayed"] is False
    assert body["amount"] == "180.00"
    assert body["obligation"]["status"] == "paid"
    assert body["obligation"]["paid_amount"] == "180.00"
    assert body["obligation"]["expected_amount"] == "200.00"
    entry = client.get(f"/transactions/{body['entry_id']}").json()
    assert entry["kind"] == "expense"
    assert entry["category_id"] == salary["id"]
    assert entry["account_id"] == account["id"]
    assert entry["description"] == "Internet"
    assert balance_of(client, account["id"])["balance"] == "-180.00"
    other = create_payable(client, csrf, description="Energia", category_id=salary["id"])
    overridden = pay(
        client,
        csrf,
        other["id"],
        account["id"],
        category_id=market["id"],
        key="pago-2",
    )
    assert overridden.status_code == 201, overridden.text
    moved = client.get(f"/transactions/{overridden.json()['entry_id']}").json()
    assert moved["category_id"] == market["id"]


def test_payment_requires_category_when_the_obligation_has_none(client):
    _user, csrf = register(client)
    account = default_account(client)
    obligation = create_payable(client, csrf)
    missing = pay(client, csrf, obligation["id"], account["id"], key="sem-categoria")
    assert missing.status_code == 422
    assert client.get("/transactions").json()["items"] == []


def test_replay_conflict_and_second_payment(client):
    _user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    obligation = create_payable(client, csrf, category_id=category["id"])
    first = pay(client, csrf, obligation["id"], account["id"], key="mesma-chave")
    assert first.status_code == 201
    replay = pay(client, csrf, obligation["id"], account["id"], key="mesma-chave")
    assert replay.status_code == 200
    assert replay.json()["entry_id"] == first.json()["entry_id"]
    changed = pay(client, csrf, obligation["id"], account["id"], amount="10.00", key="mesma-chave")
    assert changed.status_code == 409
    again = pay(client, csrf, obligation["id"], account["id"], key="outra-chave")
    assert again.status_code == 409
    assert len(client.get("/transactions").json()["items"]) == 1
    missing = client.post(
        f"/payables/{obligation['id']}/payments",
        json={"account_id": account["id"]},
        headers=headers(csrf),
    )
    assert missing.status_code == 422


def test_payment_failure_rolls_back_entry_settlement_and_audit(client, monkeypatch):
    user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    obligation = create_payable(client, csrf, category_id=category["id"])
    from app.schemas.payable import PaymentCreate
    from app.services import payable_service

    real = payable_service.add_audit

    def fail_pay(db, **kwargs):
        if kwargs.get("entity_type") == "payable_obligation" and kwargs.get("operation") == "pay":
            raise RuntimeError("falha injetada")
        return real(db, **kwargs)

    monkeypatch.setattr(payable_service, "add_audit", fail_pay)
    db = SessionLocal()
    try:
        current = db.get(User, uuid.UUID(user["id"]))
        try:
            payable_service.pay_obligation(
                db,
                current,
                uuid.UUID(obligation["id"]),
                PaymentCreate(account_id=uuid.UUID(account["id"])),
                "falha-1",
            )
            raise AssertionError("O pagamento deveria falhar.")
        except RuntimeError as exc:
            assert str(exc) == "falha injetada"
    finally:
        db.close()
    assert client.get("/transactions").json()["items"] == []
    assert client.get(f"/payables/{obligation['id']}").json()["status"] == "open"
    db = SessionLocal()
    try:
        assert db.scalar(select(func.count()).select_from(PayableSettlement)) == 0
        assert db.scalar(select(func.count()).select_from(FinancialEntry)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(FinancialAuditLog)
                .where(FinancialAuditLog.operation == "pay")
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(FinancialAuditLog)
                .where(
                    FinancialAuditLog.user_id == uuid.UUID(user["id"]),
                    FinancialAuditLog.entity_type == "financial_entry",
                )
            )
            == 0
        )
    finally:
        db.close()


def test_archived_obligation_keeps_history_and_blocks_payment(client):
    _user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    obligation = create_payable(client, csrf, category_id=category["id"])
    paid = pay(client, csrf, obligation["id"], account["id"], key="antes-arquivo")
    assert paid.status_code == 201
    archived = client.post(f"/payables/{obligation['id']}/archive", headers=headers(csrf))
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"
    assert archived.json()["settlements"][0]["released_at"] is None
    blocked = pay(client, csrf, obligation["id"], account["id"], key="depois-arquivo")
    assert blocked.status_code == 409
    restored = client.post(f"/payables/{obligation['id']}/reactivate", headers=headers(csrf))
    assert restored.status_code == 200
    assert restored.json()["status"] == "paid"


def test_edit_delete_restore_and_repayment_keep_both_settlements(client):
    _user, csrf = register(client)
    account = default_account(client)
    other = create_account(client, csrf, name="Nubank")
    category = create_category(client, csrf, name="Casa")
    other_category = create_category(client, csrf, name="Lazer")
    obligation = create_payable(client, csrf, category_id=category["id"], amount="120.00")
    paid = pay(client, csrf, obligation["id"], account["id"], key="original")
    entry_id = paid.json()["entry_id"]
    edited = client.patch(
        f"/transactions/{entry_id}",
        json={
            "amount": "90.00",
            "account_id": other["id"],
            "category_id": other_category["id"],
            "occurred_on": local_today().isoformat(),
            "description": "Internet corrigida",
        },
        headers=headers(csrf),
    )
    assert edited.status_code == 200, edited.text
    detail = client.get(f"/payables/{obligation['id']}").json()
    assert detail["expected_amount"] == "120.00"
    assert detail["paid_amount"] == "90.00"
    assert detail["settlements"][0]["allocated_amount"] == "90.00"
    assert detail["settlements"][0]["entry_account_id"] == other["id"]
    blocked = client.patch(
        f"/payables/{obligation['id']}",
        json={"expected_amount": "80.00"},
        headers=headers(csrf),
    )
    assert blocked.status_code == 409
    renamed = client.patch(
        f"/payables/{obligation['id']}",
        json={"description": "Internet da casa"},
        headers=headers(csrf),
    )
    assert renamed.status_code == 200
    removed = client.delete(f"/transactions/{entry_id}", headers=headers(csrf))
    assert removed.status_code == 200
    opened = client.get(f"/payables/{obligation['id']}").json()
    assert opened["status"] == "open"
    assert opened["settlements"][0]["released_at"] is not None
    assert balance_of(client, other["id"])["balance"] == "0.00"
    second = pay(client, csrf, obligation["id"], account["id"], amount="100.00", key="novo-pagamento")
    assert second.status_code == 201, second.text
    conflict = client.post(f"/transactions/{entry_id}/restore", headers=headers(csrf))
    assert conflict.status_code == 409
    history = client.get(f"/payables/{obligation['id']}").json()
    assert len(history["settlements"]) == 2
    assert history["status"] == "paid"
    assert history["paid_amount"] == "100.00"
    released = [item for item in history["settlements"] if item["released_at"] is not None]
    active = [item for item in history["settlements"] if item["released_at"] is None]
    assert len(released) == 1 and released[0]["entry_id"] == entry_id
    assert len(active) == 1 and active[0]["entry_id"] == second.json()["entry_id"]
    deleted = client.get(f"/transactions/{entry_id}?include_deleted=true")
    assert deleted.status_code == 200
    assert deleted.json()["deleted_at"] is not None
    db = SessionLocal()
    try:
        operations = db.scalars(
            select(FinancialAuditLog.operation)
            .where(FinancialAuditLog.entity_id == uuid.UUID(obligation["id"]))
            .order_by(FinancialAuditLog.created_at)
        ).all()
        assert operations == ["create", "pay", "update", "update", "release", "pay"]
        entry_operations = db.scalars(
            select(FinancialAuditLog.operation).where(
                FinancialAuditLog.entity_id == uuid.UUID(entry_id)
            )
        ).all()
        assert "restore" not in entry_operations
    finally:
        db.close()


def test_successful_restore_reuses_the_same_settlement(client):
    _user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    obligation = create_payable(client, csrf, category_id=category["id"])
    paid = pay(client, csrf, obligation["id"], account["id"], key="restaura")
    entry_id = paid.json()["entry_id"]
    settlement_id = paid.json()["settlement_id"]
    assert client.delete(f"/transactions/{entry_id}", headers=headers(csrf)).status_code == 200
    restored = client.post(f"/transactions/{entry_id}/restore", headers=headers(csrf))
    assert restored.status_code == 200, restored.text
    detail = client.get(f"/payables/{obligation['id']}").json()
    assert detail["status"] == "paid"
    assert len(detail["settlements"]) == 1
    assert detail["settlements"][0]["id"] == settlement_id
    assert detail["settlements"][0]["released_at"] is None
    assert balance_of(client, account["id"])["balance"] == "-120.00"


def test_retroactive_payment_hits_the_payment_month(client):
    _user, csrf = register(client)
    account = default_account(client)
    open_account(client, csrf, account["id"], days=40)
    category = create_category(client, csrf)
    due = local_today() - timedelta(days=20)
    paid_on = local_today() - timedelta(days=2)
    obligation = create_payable(client, csrf, category_id=category["id"], due_on=due, amount="50.00")
    assert obligation["status"] == "overdue"
    response = pay(
        client,
        csrf,
        obligation["id"],
        account["id"],
        occurred_on=paid_on.isoformat(),
        key="retroativo",
    )
    assert response.status_code == 201, response.text
    summary = client.get("/summary").json()
    assert summary["period_expense"] == "50.00"
    future = pay(
        client,
        csrf,
        create_payable(client, csrf, description="Água", category_id=category["id"])["id"],
        account["id"],
        occurred_on=(local_today() + timedelta(days=1)).isoformat(),
        key="futuro",
    )
    assert future.status_code == 422


def test_database_rejects_allocation_and_delete_drift(client):
    _user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    obligation = create_payable(client, csrf, category_id=category["id"], amount="40.00")
    paid = pay(client, csrf, obligation["id"], account["id"], key="trigger")
    entry_id = uuid.UUID(paid.json()["entry_id"])
    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text("UPDATE financial_entries SET amount = amount + 10 WHERE id = :id"),
                {"id": entry_id},
            )
            transaction.commit()
            raise AssertionError("A trigger deveria recusar a soma divergente.")
        except IntegrityError:
            transaction.rollback()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text("UPDATE financial_entries SET deleted_at = CURRENT_TIMESTAMP WHERE id = :id"),
                {"id": entry_id},
            )
            transaction.commit()
            raise AssertionError("A trigger deveria recusar a exclusão sem liberar a quitação.")
        except IntegrityError:
            transaction.rollback()
    engine.dispose()
    detail = client.get(f"/payables/{obligation['id']}").json()
    assert detail["paid_amount"] == "40.00"
    assert detail["settlements"][0]["released_at"] is None
    assert client.get(f"/transactions/{entry_id}").json()["deleted_at"] is None


def test_multiple_obligations_share_one_expense_and_restore_is_atomic(client):
    user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    first = create_payable(client, csrf, description="Outubro", category_id=category["id"])
    second = create_payable(client, csrf, description="Novembro", category_id=category["id"])
    db = SessionLocal()
    try:
        current = db.get(User, uuid.UUID(user["id"]))
        result = settle_obligations(
            db,
            current,
            account_id=uuid.UUID(account["id"]),
            category_id=uuid.UUID(category["id"]),
            occurred_on=local_today(),
            description="Internet de três meses",
            items=[
                SettlementDraft(uuid.UUID(first["id"]), Decimal("120.00")),
                SettlementDraft(uuid.UUID(second["id"]), Decimal("130.00")),
            ],
            idempotency_key="lote-interno",
        )
    finally:
        db.close()
    assert result.replayed is False
    assert result.payment.amount == "250.00"
    assert client.get(f"/payables/{first['id']}").json()["status"] == "paid"
    assert client.get(f"/payables/{second['id']}").json()["paid_amount"] == "130.00"
    assert balance_of(client, account["id"])["balance"] == "-250.00"
    entry_id = result.payment.entry_id
    changed = client.patch(
        f"/transactions/{entry_id}",
        json={"amount": "200.00"},
        headers=headers(csrf),
    )
    assert changed.status_code == 409
    assert balance_of(client, account["id"])["balance"] == "-250.00"
    assert client.delete(f"/transactions/{entry_id}", headers=headers(csrf)).status_code == 200
    assert client.get(f"/payables/{first['id']}").json()["status"] == "open"
    assert client.get(f"/payables/{second['id']}").json()["status"] == "open"
    repaid = pay(client, csrf, first["id"], account["id"], key="so-outubro")
    assert repaid.status_code == 201
    conflict = client.post(f"/transactions/{entry_id}/restore", headers=headers(csrf))
    assert conflict.status_code == 409
    assert client.get(f"/payables/{first['id']}").json()["status"] == "paid"
    assert client.get(f"/payables/{second['id']}").json()["status"] == "open"
    assert client.get(f"/transactions/{entry_id}").json()["deleted_at"] is not None
    db = SessionLocal()
    try:
        rows = db.scalars(select(PayableSettlement).where(PayableSettlement.entry_id == entry_id)).all()
        assert len(rows) == 2
        assert all(row.released_at is not None for row in rows)
    finally:
        db.close()


def test_concurrent_payments_wait_on_the_account_and_settle_once(client):
    user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    obligation = create_payable(client, csrf, category_id=category["id"], amount="70.00")
    account_id = uuid.UUID(account["id"])
    user_id = uuid.UUID(user["id"])
    holder = AccountLock(account_id)

    def worker(key: str):
        db = SessionLocal()
        try:
            db.execute(text("SET lock_timeout = '20s'"))
            current = db.get(User, user_id)
            from app.schemas.payable import PaymentCreate
            from app.services.payable_service import pay_obligation

            return pay_obligation(
                db,
                current,
                uuid.UUID(obligation["id"]),
                PaymentCreate(account_id=account_id),
                key,
            )
        finally:
            db.close()

    try:
        holder.acquire()
        first, first_box = start_thread(lambda: worker("concorrente-a"))
        holder.wait_for_waiter(first_box)
        observer = holder.engine.connect()
        try:
            deadline = time.monotonic() + 8
            query = None
            while time.monotonic() < deadline:
                query = observer.execute(
                    text(
                        """
                        SELECT query
                        FROM pg_stat_activity
                        WHERE datname = current_database()
                          AND pid <> pg_backend_pid()
                          AND state = 'active'
                          AND wait_event_type = 'Lock'
                          AND query ILIKE '%financial_accounts%'
                        """
                    )
                ).scalar()
                if query is not None:
                    break
                if "error" in first_box:
                    raise AssertionError(first_box["error"])
                time.sleep(0.05)
        finally:
            observer.close()
        assert query is not None
        assert "payable_obligations" not in query
        second, second_box = start_thread(lambda: worker("concorrente-b"))
        holder.release()
        first.join(timeout=10)
        second.join(timeout=10)
    finally:
        holder.close()

    assert not first.is_alive()
    assert not second.is_alive()
    outcomes = [first_box, second_box]
    assert all("error" not in box or isinstance(box["error"], FinanceError) for box in outcomes)
    successes = [box["value"] for box in outcomes if "value" in box and box["value"].replayed is False]
    failures = [box["error"] for box in outcomes if "error" in box]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].status_code == 409
    assert balance_of(client, account["id"])["balance"] == "-70.00"
    assert len(client.get(f"/payables/{obligation['id']}").json()["settlements"]) == 1


def test_expense_account_change_locks_accounts_before_obligations(client):
    user, csrf = register(client)
    origin = default_account(client)
    destination = create_account(client, csrf, name="Carteira")
    category = create_category(client, csrf)
    obligation = create_payable(client, csrf, category_id=category["id"], amount="30.00")
    paid = pay(client, csrf, obligation["id"], origin["id"], key="mover")
    entry_id = uuid.UUID(paid.json()["entry_id"])
    user_id = uuid.UUID(user["id"])
    destination_id = uuid.UUID(destination["id"])
    engine = create_engine(TEST_DATABASE_URL)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        obligation_id = uuid.UUID(obligation["id"])
        found = connection.execute(
            text("SELECT COUNT(*) FROM payable_obligations WHERE id = :id"),
            {"id": obligation_id},
        ).scalar()
        linked = connection.execute(
            text("SELECT COUNT(*) FROM payable_settlements WHERE obligation_id = :id"),
            {"id": obligation_id},
        ).scalar()
        assert (found, linked) == (1, 1)
        connection.execute(
            text("SELECT id FROM payable_obligations WHERE id = :id FOR UPDATE"),
            {"id": obligation_id},
        )
        observer = engine.connect()

        def worker():
            db = SessionLocal()
            try:
                db.execute(text("SET lock_timeout = '15s'"))
                current = db.get(User, user_id)
                return update_transaction(
                    db,
                    current,
                    entry_id,
                    TransactionUpdate(account_id=destination_id),
                )
            finally:
                db.close()

        thread, box = start_thread(worker)
        try:
            _assert_accounts_locked_before_obligation(observer)
        finally:
            observer.close()
        transaction.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert "error" not in box, box.get("error")
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()
        engine.dispose()
    moved = client.get(f"/transactions/{entry_id}").json()
    assert moved["account_id"] == destination["id"]
    assert client.get(f"/payables/{obligation['id']}").json()["paid_amount"] == "30.00"
    assert balance_of(client, destination["id"])["balance"] == "-30.00"


def test_delete_and_restore_lock_the_account_before_the_obligation(client):
    user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    obligation = create_payable(client, csrf, category_id=category["id"])
    paid = pay(client, csrf, obligation["id"], account["id"], key="excluir-lock")
    entry_id = uuid.UUID(paid.json()["entry_id"])
    user_id = uuid.UUID(user["id"])
    engine = create_engine(TEST_DATABASE_URL)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(
            text("SELECT id FROM payable_obligations WHERE id = :id FOR UPDATE"),
            {"id": uuid.UUID(obligation["id"])},
        )

        def delete_worker():
            db = SessionLocal()
            try:
                db.execute(text("SET lock_timeout = '15s'"))
                current = db.get(User, user_id)
                from app.services.finance_service import delete_transaction

                return delete_transaction(db, current, entry_id)
            finally:
                db.close()

        thread, box = start_thread(delete_worker)
        observer = engine.connect()
        try:
            _assert_accounts_locked_before_obligation(observer)
        finally:
            observer.close()
        transaction.commit()
        thread.join(timeout=10)
        assert "error" not in box, box.get("error")
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()
    assert client.get(f"/payables/{obligation['id']}").json()["status"] == "open"

    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(
            text("SELECT id FROM payable_obligations WHERE id = :id FOR UPDATE"),
            {"id": uuid.UUID(obligation["id"])},
        )

        def restore_worker():
            db = SessionLocal()
            try:
                db.execute(text("SET lock_timeout = '15s'"))
                current = db.get(User, user_id)
                from app.services.finance_service import restore_transaction

                return restore_transaction(db, current, entry_id)
            finally:
                db.close()

        thread, box = start_thread(restore_worker)
        observer = engine.connect()
        try:
            _assert_accounts_locked_before_obligation(observer)
        finally:
            observer.close()
        transaction.commit()
        thread.join(timeout=10)
        assert "error" not in box, box.get("error")
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()
        engine.dispose()
    assert client.get(f"/payables/{obligation['id']}").json()["status"] == "paid"
    assert client.get(f"/payables/{obligation['id']}").json()["settlements"][0]["released_at"] is None


def _constraint_name(exc: IntegrityError) -> str:
    diagnostic = getattr(getattr(exc, "orig", None), "diag", None)
    return getattr(diagnostic, "constraint_name", "") or ""


def _is_deadlock(exc: BaseException) -> bool:
    origin = getattr(exc, "orig", None)
    return getattr(origin, "sqlstate", "") == "40P01" or "deadlock detected" in str(exc).lower()


def _reject_sql(statement: str, params: dict) -> IntegrityError:
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(statement), params)
                transaction.commit()
            except IntegrityError as exc:
                transaction.rollback()
                return exc
            raise AssertionError("O banco aceitou uma alteração que deveria ser recusada.")
    finally:
        engine.dispose()


def _reject_user_delete_after_audit_trigger(user_id: uuid.UUID) -> IntegrityError:
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    text("ALTER TABLE financial_audit_logs DISABLE TRIGGER financial_audit_logs_immutable")
                )
                connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
                transaction.commit()
            except IntegrityError as exc:
                transaction.rollback()
                return exc
            raise AssertionError("A exclusão em cascata do usuário removeu o histórico.")
    finally:
        engine.dispose()


def _assert_audit_delete_still_rejected(user_id: uuid.UUID) -> None:
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    text("DELETE FROM financial_audit_logs WHERE user_id = :id"),
                    {"id": user_id},
                )
                transaction.commit()
            except ProgrammingError as exc:
                transaction.rollback()
                assert "financial_audit_logs e imutavel" in str(exc)
                return
            raise AssertionError("A trava de auditoria ficou desligada.")
    finally:
        engine.dispose()


def _assert_settlement_consistency() -> None:
    db = SessionLocal()
    try:
        duplicates = db.execute(
            text(
                """
                SELECT obligation_id
                FROM payable_settlements
                WHERE released_at IS NULL
                GROUP BY obligation_id
                HAVING COUNT(*) > 1
                """
            )
        ).all()
        mismatches = db.execute(
            text(
                """
                SELECT e.id
                FROM financial_entries e
                JOIN payable_settlements s ON s.entry_id = e.id
                GROUP BY e.id, e.amount, e.deleted_at, e.kind
                HAVING e.kind <> 'expense'
                    OR (
                        e.deleted_at IS NULL
                        AND COALESCE(SUM(s.allocated_amount) FILTER (WHERE s.released_at IS NULL), 0)
                            IS DISTINCT FROM e.amount
                    )
                    OR (
                        e.deleted_at IS NOT NULL
                        AND COUNT(*) FILTER (WHERE s.released_at IS NULL) <> 0
                    )
                """
            )
        ).all()
    finally:
        db.close()
    assert duplicates == []
    assert mismatches == []


def _session_call(user_id: uuid.UUID, action):
    def worker():
        db = SessionLocal()
        try:
            db.execute(text("SET lock_timeout = '20s'"))
            current = db.get(User, user_id)
            return action(db, current)
        finally:
            db.close()

    return worker


def _account_waiters(observer) -> tuple[int, list]:
    activity = observer.execute(
        text(
            """
            SELECT pid, state, wait_event_type, wait_event, left(query, 140) AS statement
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
              AND state <> 'idle'
            """
        )
    ).all()
    waiting = sum(
        1
        for row in activity
        if row.wait_event_type == "Lock" and row.statement and "financial_accounts" in row.statement.lower()
    )
    return waiting, list(activity)


def _run_on_locked_account(account_id: uuid.UUID, workers: list):
    holder = AccountLock(account_id)
    observer = holder.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    observer.execute(text("SET statement_timeout = '3s'"))
    threads: list[tuple] = []
    released = False
    try:
        holder.acquire()
        threads = [start_thread(worker) for worker in workers]
        deadline = time.monotonic() + 12
        seen = 0
        activity: list = []
        while time.monotonic() < deadline:
            seen_now, activity = _account_waiters(observer)
            seen = max(seen, seen_now)
            if seen >= len(workers):
                break
            if any(_is_deadlock(box["error"]) for _thread, box in threads if "error" in box):
                raise AssertionError("Deadlock antes de liberar a conta.")
            time.sleep(0.05)
        else:
            failures = [box.get("error") for _thread, box in threads]
            raise AssertionError(
                f"As sessões não disputaram a conta. vistas={seen} erros={failures} atividade={activity}"
            )
        holder.release()
        released = True
        for thread, _box in threads:
            thread.join(timeout=25)
            assert not thread.is_alive(), "Sessão não terminou após liberar a conta."
    finally:
        if not released and holder.transaction.is_active:
            holder.transaction.rollback()
        for thread, _box in threads:
            thread.join(timeout=25)
        observer.close()
        holder.close()
    boxes = [box for _thread, box in threads]
    for box in boxes:
        if "error" in box and _is_deadlock(box["error"]):
            raise AssertionError(f"Deadlock: {box['error']}")
    return boxes


def test_direct_settlement_changes_cannot_break_the_expense(client):
    _user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    obligation = create_payable(client, csrf, category_id=category["id"], amount="40.00")
    paid = pay(client, csrf, obligation["id"], account["id"], key="direto")
    entry_id = uuid.UUID(paid.json()["entry_id"])
    settlement_id = uuid.UUID(paid.json()["settlement_id"])
    drifted = _reject_sql(
        "UPDATE payable_settlements SET allocated_amount = allocated_amount + 1 WHERE id = :id",
        {"id": settlement_id},
    )
    assert _constraint_name(drifted) == "ck_payable_allocation_balance"
    assert "payable allocation does not match expense" in str(drifted)
    assert client.get(f"/payables/{obligation['id']}").json()["paid_amount"] == "40.00"

    assert client.delete(f"/transactions/{entry_id}", headers=headers(csrf)).status_code == 200
    reactivated = _reject_sql(
        "UPDATE payable_settlements SET released_at = NULL WHERE id = :id",
        {"id": settlement_id},
    )
    assert _constraint_name(reactivated) == "ck_payable_allocation_balance"
    assert "deleted expense has active payable allocation" in str(reactivated)
    released = client.get(f"/payables/{obligation['id']}").json()["settlements"][0]
    assert released["released_at"] is not None
    assert client.get(f"/transactions/{entry_id}").json()["deleted_at"] is not None

    second = pay(client, csrf, obligation["id"], account["id"], key="segunda-quitacao")
    assert second.status_code == 201, second.text
    other = post_entry(
        client,
        csrf,
        account["id"],
        category["id"],
        "expense",
        "40.00",
        local_today().isoformat(),
    )
    duplicate = _reject_sql(
        """
        INSERT INTO payable_settlements (id, user_id, obligation_id, entry_id, allocated_amount)
        SELECT gen_random_uuid(), user_id, :obligation_id, :entry_id, 40
        FROM payable_obligations
        WHERE id = :obligation_id
        """,
        {"obligation_id": uuid.UUID(obligation["id"]), "entry_id": uuid.UUID(other["id"])},
    )
    assert _constraint_name(duplicate) == "uq_payable_settlements_one_active"
    reopened = _reject_sql(
        "UPDATE payable_settlements SET released_at = NULL WHERE id = :id",
        {"id": settlement_id},
    )
    assert _constraint_name(reopened) == "uq_payable_settlements_one_active"
    history = client.get(f"/payables/{obligation['id']}").json()
    assert len([item for item in history["settlements"] if item["released_at"] is None]) == 1
    _assert_settlement_consistency()


def test_physical_settlement_delete_preserves_history(client):
    user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    obligation = create_payable(client, csrf, category_id=category["id"], amount="40.00")
    paid = pay(client, csrf, obligation["id"], account["id"], key="apaga-quitacao")
    assert paid.status_code == 201, paid.text
    settlement_id = paid.json()["settlement_id"]
    entry_id = paid.json()["entry_id"]

    active_delete = _reject_sql(
        "DELETE FROM payable_settlements WHERE id = :id",
        {"id": uuid.UUID(settlement_id)},
    )
    assert _constraint_name(active_delete) == "ck_payable_settlements_no_delete"
    assert "payable settlement history cannot be deleted" in str(active_delete)
    detail = client.get(f"/payables/{obligation['id']}").json()
    assert detail["status"] == "paid"
    assert detail["paid_amount"] == "40.00"
    assert [item["id"] for item in detail["settlements"]] == [settlement_id]
    assert detail["settlements"][0]["released_at"] is None
    assert balance_of(client, account["id"])["balance"] == "-40.00"

    assert client.delete(f"/transactions/{entry_id}", headers=headers(csrf)).status_code == 200
    released_delete = _reject_sql(
        "DELETE FROM payable_settlements WHERE id = :id",
        {"id": uuid.UUID(settlement_id)},
    )
    assert _constraint_name(released_delete) == "ck_payable_settlements_no_delete"
    released = client.get(f"/payables/{obligation['id']}").json()
    assert released["status"] == "open"
    assert released["settlements"][0]["id"] == settlement_id
    assert released["settlements"][0]["released_at"] is not None
    assert client.get(f"/transactions/{entry_id}").json()["deleted_at"] is not None

    restored = client.post(f"/transactions/{entry_id}/restore", headers=headers(csrf))
    assert restored.status_code == 200, restored.text
    history = client.get(f"/payables/{obligation['id']}").json()
    assert history["status"] == "paid"
    assert history["settlements"][0]["id"] == settlement_id
    assert history["settlements"][0]["released_at"] is None
    assert balance_of(client, account["id"])["balance"] == "-40.00"

    cascade = _reject_user_delete_after_audit_trigger(uuid.UUID(user["id"]))
    assert _constraint_name(cascade) == "ck_payable_settlements_no_delete"
    assert "payable settlement history cannot be deleted" in str(cascade)
    assert client.get(f"/payables/{obligation['id']}").json()["settlements"][0]["id"] == settlement_id
    assert client.get("/accounts").status_code == 200
    _assert_audit_delete_still_rejected(uuid.UUID(user["id"]))


def test_delete_and_new_payment_do_not_deadlock_or_duplicate(client):
    user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    obligation = create_payable(client, csrf, category_id=category["id"], amount="120.00")
    paid = pay(client, csrf, obligation["id"], account["id"], key="base-exclusao")
    entry_id = uuid.UUID(paid.json()["entry_id"])
    user_id = uuid.UUID(user["id"])
    obligation_id = uuid.UUID(obligation["id"])
    account_id = uuid.UUID(account["id"])
    boxes = _run_on_locked_account(
        account_id,
        [
            _session_call(user_id, lambda db, current: delete_transaction(db, current, entry_id)),
            _session_call(
                user_id,
                lambda db, current: pay_obligation(
                    db,
                    current,
                    obligation_id,
                    PaymentCreate(account_id=account_id),
                    "pagamento-contra-exclusao",
                ),
            ),
        ],
    )
    delete_box, pay_box = boxes
    assert "error" not in delete_box, delete_box.get("error")
    if "error" in pay_box:
        assert isinstance(pay_box["error"], FinanceError)
        assert pay_box["error"].status_code == 409
        assert balance_of(client, account["id"])["balance"] == "0.00"
        detail = client.get(f"/payables/{obligation['id']}").json()
        assert detail["status"] == "open"
        assert len(detail["settlements"]) == 1
        assert detail["settlements"][0]["released_at"] is not None
    else:
        assert pay_box["value"].replayed is False
        assert balance_of(client, account["id"])["balance"] == "-120.00"
        detail = client.get(f"/payables/{obligation['id']}").json()
        assert detail["status"] == "paid"
        assert detail["paid_amount"] == "120.00"
        assert len(detail["settlements"]) == 2
        assert client.get(f"/transactions/{entry_id}").json()["deleted_at"] is not None
    _assert_settlement_consistency()


def test_restore_and_new_payment_leave_one_active_settlement(client):
    user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    obligation = create_payable(client, csrf, category_id=category["id"], amount="120.00")
    paid = pay(client, csrf, obligation["id"], account["id"], key="base-restauro")
    entry_id = uuid.UUID(paid.json()["entry_id"])
    assert client.delete(f"/transactions/{entry_id}", headers=headers(csrf)).status_code == 200
    user_id = uuid.UUID(user["id"])
    obligation_id = uuid.UUID(obligation["id"])
    account_id = uuid.UUID(account["id"])
    boxes = _run_on_locked_account(
        account_id,
        [
            _session_call(user_id, lambda db, current: restore_transaction(db, current, entry_id)),
            _session_call(
                user_id,
                lambda db, current: pay_obligation(
                    db,
                    current,
                    obligation_id,
                    PaymentCreate(account_id=account_id),
                    "pagamento-contra-restauro",
                ),
            ),
        ],
    )
    restore_box, pay_box = boxes
    restore_ok = "error" not in restore_box
    pay_ok = "error" not in pay_box
    assert restore_ok != pay_ok
    if not restore_ok:
        assert isinstance(restore_box["error"], FinanceError)
        assert restore_box["error"].status_code == 409
    if not pay_ok:
        assert isinstance(pay_box["error"], FinanceError)
        assert pay_box["error"].status_code == 409
    detail = client.get(f"/payables/{obligation['id']}").json()
    active = [item for item in detail["settlements"] if item["released_at"] is None]
    assert detail["status"] == "paid"
    assert len(active) == 1
    assert balance_of(client, account["id"])["balance"] == "-120.00"
    deleted = client.get(f"/transactions/{entry_id}").json()
    assert (deleted["deleted_at"] is None) is restore_ok
    _assert_settlement_consistency()


def test_linked_edit_and_another_entry_commit_without_deadlock(client):
    user, csrf = register(client)
    account = default_account(client)
    category = create_category(client, csrf)
    obligation = create_payable(client, csrf, category_id=category["id"], amount="120.00")
    paid = pay(client, csrf, obligation["id"], account["id"], key="base-edicao")
    entry_id = uuid.UUID(paid.json()["entry_id"])
    user_id = uuid.UUID(user["id"])
    account_id = uuid.UUID(account["id"])
    category_id = uuid.UUID(category["id"])
    boxes = _run_on_locked_account(
        account_id,
        [
            _session_call(
                user_id,
                lambda db, current: update_transaction(
                    db,
                    current,
                    entry_id,
                    TransactionUpdate(amount=Decimal("80.00")),
                ),
            ),
            _session_call(
                user_id,
                lambda db, current: create_transaction(
                    db,
                    current,
                    TransactionCreate(
                        account_id=account_id,
                        category_id=category_id,
                        kind="expense",
                        amount=Decimal("15.00"),
                        occurred_on=local_today(),
                    ),
                ),
            ),
        ],
    )
    assert all("error" not in box for box in boxes), [box.get("error") for box in boxes]
    detail = client.get(f"/payables/{obligation['id']}").json()
    assert detail["paid_amount"] == "80.00"
    assert detail["settlements"][0]["allocated_amount"] == "80.00"
    assert client.get(f"/transactions/{entry_id}").json()["amount"] == "80.00"
    assert balance_of(client, account["id"])["balance"] == "-95.00"
    _assert_settlement_consistency()
