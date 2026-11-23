"""contas a pagar."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_payables"
down_revision: str | None = "0002_financial_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_financial_entries_id_user",
        "financial_entries",
        ["id", "user_id"],
    )
    op.create_table(
        "payable_obligations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.String(length=160), nullable=False),
        sa.Column("expected_amount", sa.Numeric(19, 2), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint("expected_amount > 0", name="ck_payable_obligations_amount"),
        sa.CheckConstraint(
            "char_length(btrim(description)) BETWEEN 1 AND 160",
            name="ck_payable_obligations_description",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_payable_obligations_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_payable_obligations_category",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_payable_obligations_id_user"),
    )
    op.create_index(
        "ix_payable_obligations_user_due",
        "payable_obligations",
        ["user_id", "due_on", "id"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_table(
        "payable_settlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("allocated_amount", sa.Numeric(19, 2), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("allocated_amount > 0", name="ck_payable_settlements_amount"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_payable_settlements_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["obligation_id", "user_id"],
            ["payable_obligations.id", "payable_obligations.user_id"],
            name="fk_payable_settlements_obligation",
        ),
        sa.ForeignKeyConstraint(
            ["entry_id", "user_id"],
            ["financial_entries.id", "financial_entries.user_id"],
            name="fk_payable_settlements_entry",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entry_id",
            "obligation_id",
            name="uq_payable_settlements_entry_obligation",
        ),
    )
    op.create_index(
        "uq_payable_settlements_one_active",
        "payable_settlements",
        ["obligation_id"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )
    op.create_index("ix_payable_settlements_entry", "payable_settlements", ["entry_id"])
    op.create_table(
        "payable_idempotency_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_payable_idempotency_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["obligation_id", "user_id"],
            ["payable_obligations.id", "payable_obligations.user_id"],
            name="fk_payable_idempotency_obligation",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["entry_id", "user_id"],
            ["financial_entries.id", "financial_entries.user_id"],
            name="fk_payable_idempotency_entry",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_payable_idempotency_user_key"),
    )
    op.execute(
        """
        CREATE FUNCTION assert_payable_allocation_balance()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        DECLARE
            target uuid;
            entry_amount numeric;
            entry_deleted timestamptz;
            entry_kind text;
            active_sum numeric;
            active_count integer;
            any_count integer;
        BEGIN
            IF TG_TABLE_NAME = 'financial_entries' THEN
                target := NEW.id;
            ELSE
                target := COALESCE(NEW.entry_id, OLD.entry_id);
            END IF;

            SELECT amount, deleted_at, kind
              INTO entry_amount, entry_deleted, entry_kind
              FROM financial_entries
             WHERE id = target;

            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            SELECT COALESCE(SUM(allocated_amount) FILTER (WHERE released_at IS NULL), 0),
                   COUNT(*) FILTER (WHERE released_at IS NULL),
                   COUNT(*)
              INTO active_sum, active_count, any_count
              FROM payable_settlements
             WHERE entry_id = target;

            IF any_count = 0 THEN
                RETURN NULL;
            END IF;

            IF entry_kind <> 'expense' THEN
                RAISE EXCEPTION 'payable allocation requires expense'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_payable_allocation_balance';
            END IF;

            IF entry_deleted IS NOT NULL THEN
                IF active_count <> 0 THEN
                    RAISE EXCEPTION 'deleted expense has active payable allocation'
                        USING ERRCODE = '23514', CONSTRAINT = 'ck_payable_allocation_balance';
                END IF;
                RETURN NULL;
            END IF;

            IF active_count < 1 OR active_sum <> entry_amount THEN
                RAISE EXCEPTION 'payable allocation does not match expense'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_payable_allocation_balance';
            END IF;

            RETURN NULL;
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER payable_settlements_allocation_balance
        AFTER INSERT OR UPDATE OR DELETE ON payable_settlements
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION assert_payable_allocation_balance()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER financial_entries_allocation_balance
        AFTER UPDATE OF amount, deleted_at ON financial_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION assert_payable_allocation_balance()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_payable_settlement_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        BEGIN
            RAISE EXCEPTION 'payable settlement history cannot be deleted'
                USING ERRCODE = '23001', CONSTRAINT = 'ck_payable_settlements_no_delete';
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER payable_settlements_no_delete
        BEFORE DELETE ON payable_settlements
        FOR EACH ROW
        EXECUTE FUNCTION reject_payable_settlement_delete()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS payable_settlements_no_delete ON payable_settlements")
    op.execute("DROP FUNCTION IF EXISTS reject_payable_settlement_delete()")
    op.execute(
        "DROP TRIGGER IF EXISTS financial_entries_allocation_balance ON financial_entries"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS payable_settlements_allocation_balance ON payable_settlements"
    )
    op.execute("DROP FUNCTION IF EXISTS assert_payable_allocation_balance()")
    op.drop_table("payable_idempotency_keys")
    op.drop_index("ix_payable_settlements_entry", table_name="payable_settlements")
    op.drop_index("uq_payable_settlements_one_active", table_name="payable_settlements")
    op.drop_table("payable_settlements")
    op.drop_index("ix_payable_obligations_user_due", table_name="payable_obligations")
    op.drop_table("payable_obligations")
    op.drop_constraint("uq_financial_entries_id_user", "financial_entries", type_="unique")
