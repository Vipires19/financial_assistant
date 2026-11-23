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


class PayableObligation(Base):
    __tablename__ = "payable_obligations"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_payable_obligations_id_user"),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_payable_obligations_user_id",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_payable_obligations_category",
        ),
        CheckConstraint("expected_amount > 0", name="ck_payable_obligations_amount"),
        CheckConstraint(
            "char_length(btrim(description)) BETWEEN 1 AND 160",
            name="ck_payable_obligations_description",
        ),
        Index(
            "ix_payable_obligations_user_due",
            "user_id",
            "due_on",
            "id",
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    description: Mapped[str] = mapped_column(String(160))
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(19, 2))
    due_on: Mapped[date] = mapped_column(Date)
    category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PayableSettlement(Base):
    __tablename__ = "payable_settlements"
    __table_args__ = (
        UniqueConstraint("entry_id", "obligation_id", name="uq_payable_settlements_entry_obligation"),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_payable_settlements_user_id",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["obligation_id", "user_id"],
            ["payable_obligations.id", "payable_obligations.user_id"],
            name="fk_payable_settlements_obligation",
        ),
        ForeignKeyConstraint(
            ["entry_id", "user_id"],
            ["financial_entries.id", "financial_entries.user_id"],
            name="fk_payable_settlements_entry",
        ),
        CheckConstraint("allocated_amount > 0", name="ck_payable_settlements_amount"),
        Index(
            "uq_payable_settlements_one_active",
            "obligation_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
        Index("ix_payable_settlements_entry", "entry_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    obligation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    entry_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(19, 2))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PayableIdempotencyKey(Base):
    __tablename__ = "payable_idempotency_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_payable_idempotency_user_key"),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_payable_idempotency_user_id",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["obligation_id", "user_id"],
            ["payable_obligations.id", "payable_obligations.user_id"],
            name="fk_payable_idempotency_obligation",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["entry_id", "user_id"],
            ["financial_entries.id", "financial_entries.user_id"],
            name="fk_payable_idempotency_entry",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    obligation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    entry_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
