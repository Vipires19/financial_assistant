"""
Plano de recursos (individual vs família), limites e mensagens de monetização.

Fonte única de verdade: use sempre ``get_plano_recursos`` (backend, context, APIs).

- ``tipo_plano`` explícito no documento do usuário tem prioridade.
- Fallback: ``assinatura.plano`` em ``familia_mensal`` / ``familia_anual`` → recursos família.
- Fallback legado: campo raiz ``plano`` apenas se for ``individual`` | ``familia`` (evita confundir com trial/mensal).

``assinatura.plano`` (billing) e ``tipo_plano`` (recursos) devem ser mantidos alinhados ao escolher plano
(ver view ``escolher_plano_recursos``).

Localização: core/services/plan_service.py
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Recursos (produto)
PLAN_INDIVIDUAL = "individual"
PLAN_FAMILIA = "familia"
VALID_PLANOS_RECURSOS = (PLAN_INDIVIDUAL, PLAN_FAMILIA)

# Limites de membros por plano de recursos (future-proof: basic 3, pro 10, etc.)
PLAN_LIMITS: Dict[str, int] = {
    PLAN_INDIVIDUAL: 1,
    PLAN_FAMILIA: 5,
}

# Billing → recursos (quando ``tipo_plano`` não está definido)
BILLING_PLANOS_FAMILIA = frozenset({"familia_mensal", "familia_anual"})

MSG_UPGRADE_FAMILIA = (
    "Faça upgrade para o plano família para compartilhar o controle financeiro."
)

ERR_CRIAR_FAMILIA_PLANO = (
    "Seu plano atual não permite criar uma família. " + MSG_UPGRADE_FAMILIA
)
ERR_CONVIDAR_PLANO = (
    "Seu plano atual não permite adicionar membros.\n\n"
    "👉 Faça upgrade para o plano família e compartilhe o controle financeiro com outras pessoas."
)

ERR_DOWNGRADE_INDIVIDUAL_COM_FAMILIA = (
    "Você ainda faz parte de uma família. Saia da família antes de voltar ao plano individual."
)

ERR_ACESSO_FAMILIA_EXPIRADO = (
    "Seu acesso ao plano família expirou. Renove o plano para criar ou convidar novamente."
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_end_acesso(dt: Any) -> Optional[datetime]:
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo:
        return dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=timezone.utc)


def usuario_tem_acesso_familia(user: Optional[Dict[str, Any]]) -> bool:
    """
    True se o usuário pode usar recursos do plano família (criar grupo, convidar),
    respeitando cancelamento com acesso até ``data_fim_acesso``.
    """
    if not user:
        return False
    if user.get("tipo_plano") != PLAN_FAMILIA:
        return False
    if user.get("cancelamento_agendado"):
        fim = user.get("data_fim_acesso")
        end = _normalize_end_acesso(fim)
        if end is None:
            return False
        return _now_utc() <= end
    return True


def get_plano_recursos(user: Optional[Dict[str, Any]]) -> str:
    """
    Retorna ``individual`` ou ``familia`` (única fonte de verdade para regras de produto).
    """
    if not user:
        return PLAN_INDIVIDUAL
    tp = user.get("tipo_plano")
    if tp in VALID_PLANOS_RECURSOS:
        return tp
    assinatura = user.get("assinatura") or {}
    plano_assinatura = assinatura.get("plano")
    if plano_assinatura in BILLING_PLANOS_FAMILIA:
        return PLAN_FAMILIA
    leg = user.get("plano")
    if leg in VALID_PLANOS_RECURSOS:
        return leg
    return PLAN_INDIVIDUAL


def get_limite_membros(user: Optional[Dict[str, Any]]) -> int:
    """Limite de membros na família conforme o plano de recursos efetivo."""
    key = get_plano_recursos(user)
    return PLAN_LIMITS.get(key, PLAN_LIMITS[PLAN_INDIVIDUAL])


def is_family_read_only(user: Optional[Dict[str, Any]]) -> bool:
    """
    Plano individual (recursos) mas ainda vinculado a uma família — só leitura / sem convidar.

    Tipico após downgrade de ``tipo_plano`` sem sair do grupo.
    """
    if not user or not user.get("family_group_id"):
        return False
    return get_plano_recursos(user) != PLAN_FAMILIA


def validate_tipo_plano_individual(user: Optional[Dict[str, Any]]) -> None:
    """Antes de gravar ``tipo_plano: individual`` — bloqueia se ainda estiver em família."""
    if not user:
        return
    if user.get("family_group_id"):
        raise ValueError(ERR_DOWNGRADE_INDIVIDUAL_COM_FAMILIA)
