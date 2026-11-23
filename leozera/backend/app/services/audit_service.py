import uuid

from sqlalchemy.orm import Session

from app.models.financial_audit import FinancialAuditLog


def add_audit(
    db: Session,
    *,
    user_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    operation: str,
    before: dict | None,
    after: dict | None,
) -> None:
    db.add(
        FinancialAuditLog(
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            operation=operation,
            before_data=before,
            after_data=after,
        )
    )
