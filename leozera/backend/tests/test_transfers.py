import threading
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.db.time import local_today
from app.models.user import User
from app.schemas.finance import TransferCreate
from app.services.finance_service import create_transfer
from tests.conftest import TEST_DATABASE_URL
from tests.helpers import balance_of, create_account, default_account, headers, open_account, register


def test_transfer_moves_balance_without_changing_income_or_expense(client):
    _, csrf = register(client)
    origin = default_account(client)
    destination = create_account(client, csrf, "Nubank")
    open_account(client, csrf, origin["id"])
    open_account(client, csrf, destination["id"])
    yesterday = (local_today() - timedelta(days=1)).isoformat()
    created = client.post(
        "/transfers",
        json={
            "from_account_id": origin["id"],
            "to_account_id": destination["id"],
            "amount": "500.00",
            "occurred_on": yesterday,
        },
        headers=headers(csrf),
    )
    assert created.status_code == 201, created.text
    origin_balance = balance_of(client, origin["id"])
    destination_balance = balance_of(client, destination["id"])
    assert origin_balance["balance"] == "-500.00"
    assert destination_balance["balance"] == "500.00"
    assert origin_balance["income_total"] == "0.00"
    assert origin_balance["expense_total"] == "0.00"
    assert destination_balance["income_total"] == "0.00"
    assert destination_balance["expense_total"] == "0.00"
    listed = client.get(f"/transactions?account_id={destination['id']}").json()["items"]
    assert listed[0]["kind"] == "transfer"
    assert listed[0]["effect"] == "500.00"
    same = client.post(
        "/transfers",
        json={
            "from_account_id": origin["id"],
            "to_account_id": origin["id"],
            "amount": "1.00",
            "occurred_on": yesterday,
        },
        headers=headers(csrf),
    )
    assert same.status_code == 422
    future = client.post(
        "/transfers",
        json={
            "from_account_id": origin["id"],
            "to_account_id": destination["id"],
            "amount": "1.00",
            "occurred_on": (local_today() + timedelta(days=1)).isoformat(),
        },
        headers=headers(csrf),
    )
    assert future.status_code == 422
    scaled = client.post(
        "/transfers",
        json={
            "from_account_id": origin["id"],
            "to_account_id": destination["id"],
            "amount": "1.115",
            "occurred_on": yesterday,
        },
        headers=headers(csrf),
    )
    assert scaled.status_code == 422


def test_transfer_edit_delete_and_restore(client):
    _, csrf = register(client)
    origin = default_account(client)
    destination = create_account(client, csrf, "Nubank")
    wallet = create_account(client, csrf, "Carteira")
    today = local_today().isoformat()
    created = client.post(
        "/transfers",
        json={
            "from_account_id": origin["id"],
            "to_account_id": destination["id"],
            "amount": "40.00",
            "occurred_on": today,
        },
        headers=headers(csrf),
    )
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]
    edited = client.patch(
        f"/transfers/{entry_id}",
        json={"amount": "15.00", "to_account_id": wallet["id"]},
        headers=headers(csrf),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["id"] == entry_id
    assert balance_of(client, origin["id"])["balance"] == "-15.00"
    assert balance_of(client, destination["id"])["balance"] == "0.00"
    assert balance_of(client, wallet["id"])["balance"] == "15.00"
    removed = client.delete(f"/transfers/{entry_id}", headers=headers(csrf))
    assert removed.status_code == 200
    assert balance_of(client, origin["id"])["balance"] == "0.00"
    assert balance_of(client, wallet["id"])["balance"] == "0.00"
    restored = client.post(f"/transfers/{entry_id}/restore", headers=headers(csrf))
    assert restored.status_code == 200
    assert balance_of(client, wallet["id"])["balance"] == "15.00"
    wrong_route = client.patch(f"/transactions/{entry_id}", json={"amount": "1.00"}, headers=headers(csrf))
    assert wrong_route.status_code == 409


def test_missing_destination_does_not_persist_a_transfer(client):
    _, csrf = register(client)
    origin = default_account(client)
    response = client.post(
        "/transfers",
        json={
            "from_account_id": origin["id"],
            "to_account_id": str(uuid.uuid4()),
            "amount": "10.00",
            "occurred_on": local_today().isoformat(),
        },
        headers=headers(csrf),
    )
    assert response.status_code == 404
    assert client.get("/transactions").json()["items"] == []


def test_database_rejects_a_transfer_without_destination(client):
    register(client)
    account = default_account(client)
    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as connection:
        transaction = connection.begin()
        user_id = connection.execute(text("SELECT id FROM users")).scalar()
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO financial_entries (
                        id, user_id, kind, account_id, amount, occurred_on
                    ) VALUES (
                        :id, :user_id, 'transfer', :account_id, 10.00, CURRENT_DATE
                    )
                    """
                ),
                {"id": uuid.uuid4(), "user_id": user_id, "account_id": account["id"]},
            )
        transaction.rollback()
    engine.dispose()


def test_opposite_transfers_do_not_deadlock(client):
    user, _csrf = register(client)
    origin = default_account(client)
    destination = create_account(client, _csrf, "Nubank")
    user_id = uuid.UUID(user["id"])
    origin_id = uuid.UUID(origin["id"])
    destination_id = uuid.UUID(destination["id"])
    barrier = threading.Barrier(2)
    today = local_today()

    def move(source: uuid.UUID, target: uuid.UUID) -> None:
        barrier.wait(timeout=5)
        db = SessionLocal()
        try:
            db.execute(text("SET lock_timeout = '8s'"))
            current = db.get(User, user_id)
            create_transfer(
                db,
                current,
                TransferCreate(
                    from_account_id=source,
                    to_account_id=target,
                    amount=Decimal("10.00"),
                    occurred_on=today,
                ),
            )
        finally:
            db.close()

    first, box_first = _thread(lambda: move(origin_id, destination_id))
    second, box_second = _thread(lambda: move(destination_id, origin_id))
    first.join(timeout=15)
    second.join(timeout=15)
    assert not first.is_alive()
    assert not second.is_alive()
    assert "error" not in box_first, box_first.get("error")
    assert "error" not in box_second, box_second.get("error")
    assert balance_of(client, origin["id"])["balance"] == "0.00"
    assert balance_of(client, destination["id"])["balance"] == "0.00"


def _thread(action):
    from tests.helpers import start_thread

    return start_thread(action)
