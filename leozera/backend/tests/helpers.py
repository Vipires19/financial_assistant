import threading
import time
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from app.db.time import local_today
from tests.conftest import TEST_DATABASE_URL, auth_headers


def headers(csrf: str) -> dict[str, str]:
    return auth_headers(csrf)


def register(client, *, name="André", email="andre@example.com", password="senha-segura-1"):
    response = client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password},
        headers=auth_headers(),
    )
    assert response.status_code == 201, response.text
    return response.json(), response.cookies["leozera_csrf"]


def default_account(client) -> dict:
    response = client.get("/accounts")
    assert response.status_code == 200, response.text
    return next(item for item in response.json() if item["is_default"])


def create_account(client, csrf, name="Nubank", initial="0.00", opened_on: date | None = None) -> dict:
    payload: dict = {"name": name, "initial_balance": initial}
    if opened_on is not None:
        payload["opened_on"] = opened_on.isoformat()
    response = client.post("/accounts", json=payload, headers=headers(csrf))
    assert response.status_code == 201, response.text
    return response.json()


def create_category(client, csrf, name="Mercado") -> dict:
    response = client.post("/categories", json={"name": name}, headers=headers(csrf))
    assert response.status_code == 201, response.text
    return response.json()


def open_account(client, csrf, account_id: str, days: int = 30) -> str:
    opened = (local_today() - timedelta(days=days)).isoformat()
    response = client.patch(
        f"/accounts/{account_id}",
        json={"opened_on": opened},
        headers=headers(csrf),
    )
    assert response.status_code == 200, response.text
    return opened


def post_entry(client, csrf, account_id, category_id, kind, amount, occurred_on, description=None):
    payload = {
        "account_id": account_id,
        "category_id": category_id,
        "kind": kind,
        "amount": amount,
        "occurred_on": occurred_on,
    }
    if description is not None:
        payload["description"] = description
    response = client.post("/transactions", json=payload, headers=headers(csrf))
    assert response.status_code == 201, response.text
    return response.json()


def balance_of(client, account_id: str, on: str | None = None) -> dict:
    url = f"/accounts/{account_id}/balance"
    if on is not None:
        url = f"{url}?on={on}"
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.json()


def start_thread(action: Callable[[], object]) -> tuple[threading.Thread, dict]:
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = action()
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    return thread, box


class AccountLock:
    def __init__(self, account_id: uuid.UUID) -> None:
        self.account_id = account_id
        self.engine: Engine = create_engine(TEST_DATABASE_URL)
        self.conn: Connection = self.engine.connect()
        self.transaction = self.conn.begin()

    def acquire(self) -> None:
        self.conn.execute(
            text("SELECT id FROM financial_accounts WHERE id = :id FOR UPDATE"),
            {"id": self.account_id},
        )

    def wait_for_waiter(self, box: dict, timeout: float = 8.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            waiting = self.conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM pg_stat_activity
                    WHERE pid <> pg_backend_pid()
                      AND datname = current_database()
                      AND wait_event_type = 'Lock'
                    """
                )
            ).scalar()
            if waiting:
                return
            if "error" in box:
                raise AssertionError(box["error"])
            time.sleep(0.05)
        activity = self.conn.execute(
            text(
                """
                SELECT pid, state, wait_event_type, wait_event, left(query, 180)
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                """
            )
        ).all()
        locks = self.conn.execute(
            text(
                """
                SELECT locktype, mode, granted
                FROM pg_locks
                WHERE pid <> pg_backend_pid()
                """
            )
        ).all()
        raise AssertionError(f"A outra transação não ficou bloqueada. estado={box} activity={activity} locks={locks}")

    def execute(self, statement: str, params: dict | None = None):
        return self.conn.execute(text(statement), params or {})

    def release(self) -> None:
        self.transaction.commit()

    def close(self) -> None:
        if self.transaction.is_active:
            self.transaction.rollback()
        self.conn.close()
        self.engine.dispose()


def money(value: Decimal | str) -> str:
    return format(Decimal(value).quantize(Decimal("0.01")), "f")
