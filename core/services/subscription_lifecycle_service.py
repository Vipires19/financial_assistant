"""
Downgrade automático após término do período pago (grace) — cron / management command.

Não remove família nem membros; apenas ``tipo_plano`` → individual e bloqueia convites novos.

Localização: core/services/subscription_lifecycle_service.py
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

from core.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


def aplicar_downgrade_para_individual(usuario: Dict[str, Any]) -> None:
    """Após ``data_fim_acesso``: recursos individuais; dados da família permanecem."""
    repo = UserRepository()
    uid = usuario["_id"]
    now = datetime.utcnow()
    repo.collection.update_one(
        {"_id": uid},
        {
            "$set": {
                "tipo_plano": "individual",
                "status_pagamento": "cancelado",
                "cancelamento_agendado": False,
                "status_assinatura": "encerrada",
                "assinatura.status": "encerrada",
                "updated_at": now,
            },
            "$unset": {"data_fim_acesso": ""},
        },
    )
    logger.info("event=subscription_downgrade_grace_end user_id=%s", uid)


def processar_downgrades_pendentes() -> int:
    """
    Usuários com cancelamento agendado e ``data_fim_acesso`` no passado.
    Retorna quantidade processada.
    """
    repo = UserRepository()
    # UTC naive — alinhado ao restante do projeto / BSON
    now = datetime.utcnow()
    query = {"cancelamento_agendado": True, "data_fim_acesso": {"$lt": now}}
    n = 0
    for doc in repo.collection.find(query):
        try:
            aplicar_downgrade_para_individual(doc)
            n += 1
        except Exception as e:
            logger.exception("Downgrade falhou user_id=%s: %s", doc.get("_id"), e)
    return n
