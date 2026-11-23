"""núcleo financeiro."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_financial_core"
down_revision: str | None = "0001_users_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "financial_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("initial_balance", sa.Numeric(19, 2), nullable=False),
        sa.Column("opened_on", sa.Date(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_financial_accounts_id_user"),
    )
    op.create_index(
        "ix_financial_accounts_user_archived",
        "financial_accounts",
        ["user_id", "archived_at"],
    )
    op.create_index(
        "uq_financial_accounts_one_default",
        "financial_accounts",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("group_code", sa.String(length=40), nullable=True),
        sa.Column("code", sa.String(length=40), nullable=True),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "(is_internal AND code IS NOT NULL) OR (NOT is_internal AND code IS NULL)",
            name="ck_categories_internal_code",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_categories_id_user"),
        sa.UniqueConstraint("user_id", "code", name="uq_categories_user_code"),
    )
    op.create_index("ix_categories_user_archived", "categories", ["user_id", "archived_at"])
    op.execute(
        "CREATE UNIQUE INDEX uq_categories_user_lower_name ON categories (user_id, lower(name))"
    )
    op.create_table(
        "financial_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("counter_account_id", sa.Uuid(), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.Numeric(19, 2), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "kind IN ('income', 'expense', 'transfer', 'adjustment')",
            name="ck_financial_entries_kind",
        ),
        sa.CheckConstraint(
            """
            (
                kind IN ('income', 'expense')
                AND amount > 0
                AND category_id IS NOT NULL
                AND counter_account_id IS NULL
            ) OR (
                kind = 'transfer'
                AND amount > 0
                AND category_id IS NULL
                AND counter_account_id IS NOT NULL
                AND counter_account_id <> account_id
            ) OR (
                kind = 'adjustment'
                AND amount <> 0
                AND category_id IS NOT NULL
                AND counter_account_id IS NULL
            )
            """,
            name="ck_financial_entries_shape",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_financial_entries_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["financial_accounts.id", "financial_accounts.user_id"],
            name="fk_financial_entries_account",
        ),
        sa.ForeignKeyConstraint(
            ["counter_account_id", "user_id"],
            ["financial_accounts.id", "financial_accounts.user_id"],
            name="fk_financial_entries_counter_account",
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_financial_entries_category",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_financial_entries_user_occurred",
        "financial_entries",
        ["user_id", "occurred_on", "id"],
    )
    op.create_index(
        "ix_financial_entries_account_occurred",
        "financial_entries",
        ["account_id", "occurred_on"],
    )
    op.create_index(
        "ix_financial_entries_user_category",
        "financial_entries",
        ["user_id", "category_id"],
    )
    op.create_index(
        "ix_financial_entries_user_deleted",
        "financial_entries",
        ["user_id", "deleted_at"],
    )
    op.create_index(
        "ix_financial_entries_counter_occurred",
        "financial_entries",
        ["counter_account_id", "occurred_on"],
        postgresql_where=sa.text("counter_account_id IS NOT NULL"),
    )
    op.create_table(
        "financial_audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("before_data", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("after_data", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_financial_audit_entity",
        "financial_audit_logs",
        ["entity_type", "entity_id", "created_at"],
    )
    op.create_index("ix_financial_audit_user", "financial_audit_logs", ["user_id"])
    op.execute(
        """
        CREATE VIEW financial_entry_effects AS
        SELECT
            id AS entry_id,
            user_id,
            account_id,
            kind,
            CASE
                WHEN kind = 'income' THEN amount
                WHEN kind = 'expense' THEN -amount
                WHEN kind = 'transfer' THEN -amount
                WHEN kind = 'adjustment' THEN amount
            END AS signed_amount,
            occurred_on,
            deleted_at,
            category_id
        FROM financial_entries
        UNION ALL
        SELECT
            id AS entry_id,
            user_id,
            counter_account_id AS account_id,
            kind,
            amount AS signed_amount,
            occurred_on,
            deleted_at,
            category_id
        FROM financial_entries
        WHERE kind = 'transfer'
        """
    )
    op.execute(
        """
        CREATE FUNCTION financial_account_position(p_account_id uuid, p_as_of date)
        RETURNS TABLE (balance numeric, income_total numeric, expense_total numeric)
        LANGUAGE sql
        STABLE
        AS $function$
            SELECT
                a.initial_balance + COALESCE((
                    SELECT SUM(e.signed_amount)
                    FROM financial_entry_effects e
                    WHERE e.account_id = a.id
                      AND e.user_id = a.user_id
                      AND e.deleted_at IS NULL
                      AND e.occurred_on <= p_as_of
                ), 0::numeric),
                COALESCE((
                    SELECT SUM(en.amount)
                    FROM financial_entries en
                    WHERE en.account_id = a.id
                      AND en.user_id = a.user_id
                      AND en.deleted_at IS NULL
                      AND en.kind = 'income'
                      AND en.occurred_on <= p_as_of
                ), 0::numeric),
                COALESCE((
                    SELECT SUM(en.amount)
                    FROM financial_entries en
                    WHERE en.account_id = a.id
                      AND en.user_id = a.user_id
                      AND en.deleted_at IS NULL
                      AND en.kind = 'expense'
                      AND en.occurred_on <= p_as_of
                ), 0::numeric)
            FROM financial_accounts a
            WHERE a.id = p_account_id
              AND p_as_of >= a.opened_on
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_financial_audit_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        BEGIN
            RAISE EXCEPTION 'financial_audit_logs e imutavel';
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER financial_audit_logs_immutable
        BEFORE UPDATE OR DELETE ON financial_audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION reject_financial_audit_mutation()
        """
    )
    _provision_existing_users()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS financial_audit_logs_immutable ON financial_audit_logs")
    op.execute("DROP FUNCTION IF EXISTS reject_financial_audit_mutation()")
    op.execute("DROP FUNCTION IF EXISTS financial_account_position(uuid, date)")
    op.execute("DROP VIEW IF EXISTS financial_entry_effects")
    op.drop_index("ix_financial_audit_user", table_name="financial_audit_logs")
    op.drop_index("ix_financial_audit_entity", table_name="financial_audit_logs")
    op.drop_table("financial_audit_logs")
    op.drop_index("ix_financial_entries_counter_occurred", table_name="financial_entries")
    op.drop_index("ix_financial_entries_user_deleted", table_name="financial_entries")
    op.drop_index("ix_financial_entries_user_category", table_name="financial_entries")
    op.drop_index("ix_financial_entries_account_occurred", table_name="financial_entries")
    op.drop_index("ix_financial_entries_user_occurred", table_name="financial_entries")
    op.drop_table("financial_entries")
    op.execute("DROP INDEX IF EXISTS uq_categories_user_lower_name")
    op.drop_index("ix_categories_user_archived", table_name="categories")
    op.drop_table("categories")
    op.drop_index("uq_financial_accounts_one_default", table_name="financial_accounts")
    op.drop_index("ix_financial_accounts_user_archived", table_name="financial_accounts")
    op.drop_table("financial_accounts")


def _provision_existing_users() -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.models.user import User
    from app.services.finance_service import provision_user_finance

    connection = op.get_bind()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        for user in session.scalars(select(User)):
            provision_user_finance(session, user)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
