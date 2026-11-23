import os
import re
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://leozera:leozera@localhost:5432/leozera_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["FRONTEND_ORIGIN"] = "http://localhost:3000"

ORIGIN = "http://localhost:3000"


def auth_headers(csrf: str | None = None, origin: str | None = ORIGIN) -> dict[str, str]:
    headers: dict[str, str] = {}
    if origin is not None:
        headers["Origin"] = origin
    if csrf is not None:
        headers["X-CSRF-Token"] = csrf
    return headers


def ensure_database(url: str) -> None:
    parsed = make_url(url)
    database_name = parsed.database or ""
    if not re.fullmatch(r"[A-Za-z0-9_]+", database_name):
        raise RuntimeError("Nome de banco de teste inválido.")
    admin_engine = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": database_name},
        ).scalar()
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    admin_engine.dispose()


def upgrade_head(url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    ensure_database(TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    upgrade_head(TEST_DATABASE_URL)
    yield


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    yield
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE payable_idempotency_keys, payable_settlements, "
                "payable_obligations, financial_audit_logs, financial_entries, categories, "
                "financial_accounts, auth_sessions, users CASCADE"
            )
        )
    engine.dispose()


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
