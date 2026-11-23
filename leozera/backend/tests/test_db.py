import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import TEST_DATABASE_URL


def connection():
    engine = create_engine(TEST_DATABASE_URL)
    return engine, engine.connect()


def test_migration_creates_tables_on_clean_database():
    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as conn:
        tables = set(
            conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            ).scalars()
        )
        columns = set(
            conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'auth_sessions'"
                )
            ).scalars()
        )
        email_type = conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'users' AND column_name = 'created_at'"
            )
        ).scalar()
    engine.dispose()
    assert {"users", "auth_sessions", "alembic_version"} <= tables
    assert "csrf_token_hash" in columns
    assert email_type == "timestamp with time zone"


def test_email_uniqueness_constraint():
    engine, conn = connection()
    transaction = conn.begin()
    user_id = uuid.uuid4()
    other_id = uuid.uuid4()
    statement = text(
        """
        INSERT INTO users (id, name, email, hashed_password, is_active, created_at, updated_at)
        VALUES (:id, 'A', 'unico@example.com', 'hash', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
    )
    try:
        conn.execute(statement, {"id": user_id})
        with pytest.raises(IntegrityError):
            conn.execute(statement, {"id": other_id})
    finally:
        transaction.rollback()
        conn.close()
        engine.dispose()


def test_session_requires_existing_user():
    engine, conn = connection()
    transaction = conn.begin()
    try:
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    """
                    INSERT INTO auth_sessions (
                        id, user_id, token_hash, csrf_token_hash, created_at, expires_at
                    )
                    VALUES (
                        :id, :user_id, :token_hash, :csrf_hash, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "user_id": uuid.uuid4(),
                    "token_hash": "a" * 64,
                    "csrf_hash": "b" * 64,
                },
            )
    finally:
        transaction.rollback()
        conn.close()
        engine.dispose()
