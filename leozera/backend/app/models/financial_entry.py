import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.time import utcnow


class FinancialEntry(Base):
    __tablename__ = "financial_entries"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_financial_entries_id_user"),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_financial_entries_user_id",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["financial_accounts.id", "financial_accounts.user_id"],
            name="fk_financial_entries_account",
        ),
        ForeignKeyConstraint(
            ["counter_account_id", "user_id"],
            ["financial_accounts.id", "financial_accounts.user_id"],
            name="fk_financial_entries_counter_account",
        ),
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_financial_entries_category",
        ),
        CheckConstraint(
            "kind IN ('income', 'expense', 'transfer', 'adjustment')",
            name="ck_financial_entries_kind",
        ),
        CheckConstraint(
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
        Index("ix_financial_entries_user_occurred", "user_id", "occurred_on", "id"),
        Index("ix_financial_entries_account_occurred", "account_id", "occurred_on"),
        Index("ix_financial_entries_user_category", "user_id", "category_id"),
        Index("ix_financial_entries_user_deleted", "user_id", "deleted_at"),
        Index(
            "ix_financial_entries_counter_occurred",
            "counter_account_id",
            "occurred_on",
            postgresql_where=text("counter_account_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(16))
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    counter_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 2))
    occurred_on: Mapped[date] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(500))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
