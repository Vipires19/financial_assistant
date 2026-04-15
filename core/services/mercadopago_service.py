"""
Assinatura recorrente Mercado Pago (preapproval) — fluxo Django.

- Criação de preapproval e persistência pendente no Mongo (UserRepository).
- Webhook: sempre valida status via GET /preapproval/{id} antes de ativar plano.

Não ativar ``tipo_plano``/cobrança apenas por redirect do checkout — use webhook.

Localização: core/services/mercadopago_service.py
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import requests
from bson import ObjectId
from dateutil.parser import parse as parse_datetime
from dateutil.relativedelta import relativedelta

from core.repositories.user_repository import UserRepository
from core.services.plan_config import PLANOS
from core.services.plan_service import PLAN_FAMILIA, get_plano_recursos
from core.services.subscription_lifecycle_service import aplicar_downgrade_para_individual

logger = logging.getLogger(__name__)

MP_URL = "https://api.mercadopago.com/preapproval"


def normalizar_codigo_plano(plano: str) -> str:
    """Alias legados → códigos canônicos."""
    p = (plano or "").strip().lower()
    if p in ("mensal",):
        return "mensal_familia"
    if p in ("anual",):
        return "anual_familia"
    return p


def codigo_plano_valido(plano: str) -> bool:
    return normalizar_codigo_plano(plano) in PLANOS


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo:
        return dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=timezone.utc)


def extrair_data_fim_acesso_do_mp(mp_data: Dict[str, Any]) -> Optional[datetime]:
    """Datas comuns na resposta GET /preapproval/{id}."""
    if not mp_data:
        return None
    candidates: list[Any] = []
    for key in ("next_payment_date", "end_date"):
        v = mp_data.get(key)
        if v:
            candidates.append(v)
    summar = mp_data.get("summarized")
    if isinstance(summar, dict):
        for key in ("next_payment_date", "last_charged_date"):
            v = summar.get(key)
            if v:
                candidates.append(v)
    ar = mp_data.get("auto_recurring")
    if isinstance(ar, dict):
        for key in ("end_date", "next_payment_date"):
            v = ar.get(key)
            if v:
                candidates.append(v)
    for raw in candidates:
        if isinstance(raw, datetime):
            return _ensure_aware_utc(raw)
        if isinstance(raw, str) and raw.strip():
            try:
                return _ensure_aware_utc(parse_datetime(raw))
            except (ValueError, TypeError, OverflowError):
                continue
    return None


def calcular_fim_periodo_fallback(user: Dict[str, Any]) -> datetime:
    """Fallback quando o MP não retorna data: campos locais ou +30 dias."""
    a = user.get("assinatura") or {}
    candidates = [
        user.get("data_vencimento_plano"),
        a.get("fim"),
        a.get("proximo_vencimento"),
        user.get("data_fim_acesso"),
    ]
    for c in candidates:
        if c is None:
            continue
        if isinstance(c, datetime):
            return _ensure_aware_utc(c)
        if isinstance(c, str) and str(c).strip():
            try:
                return _ensure_aware_utc(parse_datetime(str(c)))
            except (ValueError, TypeError, OverflowError):
                continue
    return _utcnow() + timedelta(days=30)


def cancelar_preapproval_no_mp(subscription_id: str) -> None:
    token = os.getenv("MP_ACCESS_TOKEN")
    if not token:
        raise ValueError("MP_ACCESS_TOKEN não configurado")
    url = f"{MP_URL}/{subscription_id}"
    r = requests.put(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"status": "canceled"},
        timeout=15,
    )
    if r.status_code not in (200, 204):
        data = r.json() if r.text else {}
        msg = data.get("message", data.get("error", r.text or f"HTTP {r.status_code}"))
        raise RuntimeError(msg or "Erro ao cancelar no Mercado Pago")


def executar_cancelamento_pelo_usuario(user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Cancela preapproval no MP e agenda fim de acesso (grace).
    Não altera ``tipo_plano`` até ``data_fim_acesso`` (webhook/job).
    """
    assinatura = user.get("assinatura") or {}
    sid = (
        assinatura.get("gateway_subscription_id")
        or assinatura.get("mp_subscription_id")
        or user.get("mercadopago_subscription_id")
    )
    if not sid:
        raise ValueError("Assinatura Mercado Pago não encontrada.")
    if user.get("cancelamento_agendado"):
        raise ValueError("O cancelamento já está agendado.")

    cancelar_preapproval_no_mp(str(sid))
    mp_data, _err = buscar_preapproval(str(sid))
    fim = extrair_data_fim_acesso_do_mp(mp_data or {}) or calcular_fim_periodo_fallback(user)

    repo = UserRepository()
    now = _utcnow()
    repo.collection.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "cancelamento_agendado": True,
                "data_fim_acesso": fim,
                "status_pagamento": "cancelando",
                "status_assinatura": "cancelando",
                "assinatura.status": "cancelando",
                "updated_at": now,
            }
        },
    )
    return {
        "success": True,
        "message": "Assinatura cancelada. Você manterá acesso até o fim do período.",
        "data_fim_acesso": fim.isoformat().replace("+00:00", "Z"),
    }


def _fim_ja_passou(fim: Optional[datetime], now: datetime) -> bool:
    if fim is None:
        return True
    return _ensure_aware_utc(fim) <= now


def buscar_preapproval(preapproval_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """GET /preapproval/{id}. Retorna (data, erro)."""
    token = os.getenv("MP_ACCESS_TOKEN")
    if not token:
        return None, "MP_ACCESS_TOKEN não configurado"
    try:
        r = requests.get(
            f"{MP_URL}/{preapproval_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        data = r.json() if r.text else {}
        if r.status_code != 200:
            return None, data.get("message", data.get("error", r.text or f"HTTP {r.status_code}"))
        return data, None
    except requests.RequestException as e:
        logger.exception("Erro GET preapproval MP: %s", e)
        return None, str(e)


def criar_assinatura(
    user: Dict[str, Any],
    plano: str,
    *,
    back_url: str,
) -> Dict[str, Any]:
    """
    Cria preapproval no Mercado Pago e grava estado pendente no usuário.

    Returns:
        {"init_point": str, "id": str|int}
    """
    token = os.getenv("MP_ACCESS_TOKEN")
    if not token:
        raise ValueError("MP_ACCESS_TOKEN não configurado")

    cod = normalizar_codigo_plano(plano)
    cfg = PLANOS.get(cod)
    if not cfg:
        raise ValueError("Plano inválido")

    email = user.get("email")
    if not email:
        raise ValueError("Cadastre um e-mail para assinar")

    now = _utcnow()
    start = now + timedelta(minutes=5)

    payload: Dict[str, Any] = {
        "reason": f"Leozera {cfg['nome']}",
        "auto_recurring": {
            "frequency": cfg["frequency"],
            "frequency_type": cfg["frequency_type"],
            "transaction_amount": cfg["valor"],
            "currency_id": "BRL",
            "start_date": start.isoformat().replace("+00:00", "Z"),
        },
        "payer_email": email,
        "back_url": back_url,
        "status": "pending",
        "external_reference": str(user.get("_id")),
    }

    try:
        r = requests.post(
            MP_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        data = r.json() if r.text else {}
    except requests.RequestException as e:
        logger.exception("Erro POST preapproval MP: %s", e)
        raise RuntimeError(str(e)) from e

    if r.status_code not in (200, 201):
        msg = data.get("message", data.get("error", r.text or f"HTTP {r.status_code}"))
        raise RuntimeError(msg)

    init_point = data.get("init_point")
    mp_id = data.get("id")
    if not init_point or mp_id is None:
        raise RuntimeError("Resposta inválida do Mercado Pago (sem init_point ou id)")

    _persistir_preapproval_pendente(user, str(mp_id), cod)
    return {"init_point": init_point, "id": mp_id}


def _persistir_preapproval_pendente(user: Dict[str, Any], mp_id: str, plano: str) -> None:
    repo = UserRepository()
    uid = user.get("_id")
    if uid is None:
        raise ValueError("Usuário sem _id")
    now = _utcnow()
    repo.collection.update_one(
        {"_id": uid},
        {
            "$set": {
                "mercadopago_subscription_id": mp_id,
                "plano_solicitado": plano,
                "status_assinatura": "pendente_pagamento",
                "assinatura.gateway": "mercadopago",
                "assinatura.gateway_subscription_id": mp_id,
                "assinatura.plano_solicitado": plano,
                "assinatura.plano_key": plano,
                "assinatura.status": "pendente_pagamento",
                "updated_at": now,
            }
        },
    )


def extrair_preapproval_id_do_webhook(payload: Dict[str, Any]) -> Optional[str]:
    """Aceita formatos comuns de notificação MP (preapproval / subscription_preapproval)."""
    if not payload:
        return None
    data = payload.get("data")
    if isinstance(data, dict):
        rid = data.get("id")
        if rid is not None:
            return str(rid)
    if isinstance(data, str) and data.strip():
        return data.strip()
    # aninhado
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, dict) and inner.get("id") is not None:
            return str(inner["id"])
    rid = payload.get("id")
    if rid is not None:
        return str(rid)
    return None


def processar_webhook_preapproval(preapproval_id: str) -> Dict[str, Any]:
    """
    Valida preapproval no MP e atualiza usuário se ``authorized``.
    Ativa ``tipo_plano`` família + assinatura paga; encerra trial se houver.
    """
    mp_data, err = buscar_preapproval(preapproval_id)
    if err or not mp_data:
        logger.warning("Webhook MP: não foi possível validar preapproval %s: %s", preapproval_id, err)
        return {"ok": False, "error": err or "validação"}

    status_mp = (mp_data.get("status") or "").lower()
    repo = UserRepository()
    sub_id_str = str(preapproval_id)
    user = repo.collection.find_one({"mercadopago_subscription_id": sub_id_str})
    if not user:
        user = repo.collection.find_one({"assinatura.gateway_subscription_id": sub_id_str})
    if not user:
        logger.warning(
            "Webhook MP: usuário não encontrado para subscription_id=%s", preapproval_id
        )
        return {"ok": True, "ignored": True}

    now = _utcnow()
    assinatura = user.get("assinatura") or {}

    if status_mp == "authorized":
        plano_sol_raw = (
            assinatura.get("plano_solicitado")
            or user.get("plano_solicitado")
            or "mensal_familia"
        )
        plano_sol = normalizar_codigo_plano(str(plano_sol_raw))
        if plano_sol not in PLANOS:
            plano_sol = "mensal_familia"

        cfg_auth = PLANOS[plano_sol]
        tipo_recurso = cfg_auth.get("tipo_plano") or "familia"

        if cfg_auth.get("frequency_type") == "months" and int(cfg_auth.get("frequency") or 1) >= 12:
            data_vencimento = now + relativedelta(months=12)
        else:
            data_vencimento = now + relativedelta(months=1)

        subscription_id = sub_id_str

        repo.collection.update_one(
            {"_id": user["_id"]},
            {
                "$set": {
                    "plano": plano_sol,
                    "tipo_plano": tipo_recurso,
                    "status_pagamento": "ativo",
                    "status_assinatura": "ativa",
                    "data_inicio_plano": now,
                    "data_vencimento_plano": data_vencimento,
                    "mercadopago_subscription_id": subscription_id,
                    "assinatura.plano": plano_sol,
                    "assinatura.plano_key": plano_sol,
                    "assinatura.status": "ativa",
                    "assinatura.inicio": now,
                    "assinatura.fim": data_vencimento,
                    "assinatura.proximo_vencimento": data_vencimento,
                    "assinatura.gateway": "mercadopago",
                    "assinatura.gateway_subscription_id": subscription_id,
                    "assinatura.ultimo_pagamento_em": now,
                    "updated_at": now,
                },
                "$unset": {
                    "plano_solicitado": "",
                    "trial_start": "",
                    "trial_end": "",
                    "assinatura.plano_solicitado": "",
                    "cancelamento_agendado": "",
                    "data_fim_acesso": "",
                },
            },
        )
        logger.info(
            "event=mp_subscription_authorized user_id=%s plano=%s",
            user["_id"],
            plano_sol,
        )
        return {"ok": True, "activated": True}

    if status_mp == "rejected":
        repo.collection.update_one(
            {"_id": user["_id"]},
            {
                "$set": {
                    "status_assinatura": "rejeitada",
                    "assinatura.status": "rejeitada",
                    "status_pagamento": "pendente",
                    "updated_at": now,
                }
            },
        )
        logger.info("event=mp_subscription_rejected user_id=%s", user["_id"])
        return {"ok": True}

    if status_mp in ("cancelled", "paused", "expired"):
        tem_familia = get_plano_recursos(user) == PLAN_FAMILIA
        fim = extrair_data_fim_acesso_do_mp(mp_data) or calcular_fim_periodo_fallback(user)

        if not tem_familia:
            repo.collection.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {
                        "status_assinatura": status_mp,
                        "assinatura.status": status_mp,
                        "updated_at": now,
                    }
                },
            )
            logger.info(
                "event=mp_subscription_ended_no_familia user_id=%s status=%s",
                user["_id"],
                status_mp,
            )
            return {"ok": True}

        if _fim_ja_passou(fim, now):
            aplicar_downgrade_para_individual(user)
            logger.info(
                "event=mp_subscription_ended_downgrade user_id=%s status=%s",
                user["_id"],
                status_mp,
            )
            return {"ok": True, "downgraded": True}

        repo.collection.update_one(
            {"_id": user["_id"]},
            {
                "$set": {
                    "cancelamento_agendado": True,
                    "data_fim_acesso": fim,
                    "status_pagamento": "cancelando",
                    "status_assinatura": "cancelando",
                    "assinatura.status": "cancelando",
                    "updated_at": now,
                }
            },
        )
        logger.info(
            "event=mp_subscription_grace user_id=%s status_mp=%s fim=%s",
            user["_id"],
            status_mp,
            fim,
        )
        return {"ok": True, "grace": True}

    return {"ok": True}
