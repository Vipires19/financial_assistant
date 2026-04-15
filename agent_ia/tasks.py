"""
Tasks Celery para lembretes de compromissos.
Envio via WAHA centralizado em services.waha_sender (mesma lógica do app).
"""
import logging
import os
import sys
import uuid
import urllib.parse
from datetime import datetime, timedelta, time as dt_time, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytz
from bson import ObjectId
from pymongo import MongoClient
from pymongo.collection import Collection

from celery_app import celery

# Garantir import do services na raiz do projeto (financeiro)
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
_agent_ia_dir = Path(__file__).resolve().parent
if str(_agent_ia_dir) not in sys.path:
    sys.path.insert(0, str(_agent_ia_dir))
from services.waha_sender import enviar_mensagem_waha  # noqa: E402
from evaluation import avaliar_resposta  # noqa: E402
from logger import get_logger  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("worker_lembretes")
task_log = get_logger("agent_ia.tasks.lembretes")
eval_log = get_logger("agent_ia.tasks.evaluation")

# ---------------------------------------------------------------------------
# Config (sem MongoClient global)
# ---------------------------------------------------------------------------
MONGO_USER = urllib.parse.quote_plus(os.getenv("MONGO_USER", ""))
MONGO_PASS = urllib.parse.quote_plus(os.getenv("MONGO_PASS", ""))
TZ = pytz.timezone("America/Sao_Paulo")
LIMITE_12H = timedelta(hours=12)
LIMITE_1H = timedelta(hours=1)


def _resolve_trace_id(trace_id: Optional[str]) -> str:
    """Usa trace_id externo (ex.: webhook) ou gera UUID para correlação nos logs."""
    return trace_id if trace_id else str(uuid.uuid4())


def get_mongo_colls() -> Tuple[Collection, Collection, Collection]:
    """
    Retorna (compromissos, users, despesas_fixas) criando um novo MongoClient.
    Deve ser chamado dentro da task para evitar uso de cliente global após fork do Celery.
    """
    client = MongoClient(
        "mongodb+srv://%s:%s@cluster0.gjkin5a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
        % (MONGO_USER, MONGO_PASS)
    )
    db = client.financeiro_db
    return db.compromissos, db.users, db.despesas_fixas


def _observabilidade_logs_coll() -> Collection:
    """Mesmo cluster/credenciais que get_mongo_colls; apenas coleção observabilidade_logs."""
    client = MongoClient(
        "mongodb+srv://%s:%s@cluster0.gjkin5a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
        % (MONGO_USER, MONGO_PASS)
    )
    return client.financeiro_db.observabilidade_logs


def _mes_atual_str(agora_brasilia: datetime) -> str:
    """Mês civil em America/Sao_Paulo como YYYY-MM (para controle de 1 lembrete/mês)."""
    return agora_brasilia.strftime("%Y-%m")


def _filtro_nao_enviado_este_mes(agora_brasilia: datetime) -> Dict[str, Any]:
    """Documentos em que ultimo_envio_mes não marca o mês atual (ou campo ausente)."""
    mes_atual = _mes_atual_str(agora_brasilia)
    return {
        "$or": [
            {"ultimo_envio_mes": {"$exists": False}},
            {"ultimo_envio_mes": None},
            {"ultimo_envio_mes": {"$ne": mes_atual}},
        ]
    }


def _rollback_envio_mes(
    coll: Collection,
    desp_id: Any,
    valor_antigo_data: Any,
    valor_antigo_mes: Any,
) -> None:
    """Restaura ultimo_envio e ultimo_envio_mes após falha no envio."""
    try:
        set_fields: Dict[str, Any] = {}
        unset_fields: Dict[str, str] = {}
        if valor_antigo_data is None:
            unset_fields["ultimo_envio"] = ""
        else:
            set_fields["ultimo_envio"] = valor_antigo_data
        if valor_antigo_mes is None:
            unset_fields["ultimo_envio_mes"] = ""
        else:
            set_fields["ultimo_envio_mes"] = valor_antigo_mes
        update: Dict[str, Any] = {}
        if set_fields:
            update["$set"] = set_fields
        if unset_fields:
            update["$unset"] = unset_fields
        if update:
            coll.update_one({"_id": desp_id}, update)
    except Exception as e:
        logger.error("rollback envio mensal _id=%s: %s", desp_id, e)


def _formatar_moeda_brl(val: Any) -> str:
    """Valor numérico como string pt-BR (ex.: 1.234,56), para uso em mensagens."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        v = 0.0
    neg = v < 0
    v = abs(v)
    s = f"{v:.2f}"
    intp, frac = s.split(".")
    parts: list[str] = []
    while intp:
        parts.insert(0, intp[-3:])
        intp = intp[:-3]
    int_fmt = ".".join(parts)
    prefix = "-" if neg else ""
    return f"{prefix}{int_fmt},{frac}"


# Link da página de planos (env ou fallback)
LINK_PLANOS = os.getenv("LINK_PLANOS", "https://vipires19.pythonanywhere.com/planos/")


def construir_datetime_compromisso(compromisso: dict) -> Optional[datetime]:
    """
    Converte data + hora_inicio do compromisso em datetime timezone-aware (America/Sao_Paulo).
    Retorna None se faltar data ou hora_inicio.
    """
    try:
        data_field = compromisso.get("data")
        if data_field is None:
            return None
        if hasattr(data_field, "date"):
            data_val = data_field.date()
        else:
            data_val = data_field
        hora_str = compromisso.get("hora_inicio") or compromisso.get("hora")
        if not hora_str:
            return None
        parts = str(hora_str).strip().split(":")
        if len(parts) != 2:
            return None
        h, m = int(parts[0]), int(parts[1])
        t = dt_time(h, m)
        dt_naive = datetime.combine(data_val, t)
        return TZ.localize(dt_naive)
    except Exception as e:
        logger.error("construir_datetime_compromisso: %s", e)
        return None


@celery.task
def verificar_lembretes(trace_id: Optional[str] = None) -> None:
    """
    Executa a checagem de compromissos e envia lembretes (12h e 1h antes).
    Toda a lógica anterior do worker_lembretes.py está aqui.
    """
    trace_id = _resolve_trace_id(trace_id)
    task_log.info("task_start", extra={"event": "task_start", "trace_id": trace_id})
    coll_compromissos, coll_clientes, coll_despesas_fixas = get_mongo_colls()
    now = datetime.now(TZ)
    logger.info("Verificando compromissos...")

    # ----- Janela 12h: lembrete (se confirmado) ou pedido de confirmação (se não confirmado) -----
    task_log.info(
        "task_section",
        extra={
            "event": "task_section",
            "trace_id": trace_id,
            "section": "compromissos_janela_12h",
        },
    )
    cursor_12h = coll_compromissos.find({
        "status": {"$ne": "cancelado"},
        "$or": [
            {"lembrete_12h_enviado": {"$ne": True}},
            {"confirmacao_enviada": {"$ne": True}},
        ],
    })
    for comp in cursor_12h:
        try:
            dt_comp = construir_datetime_compromisso(comp)
            if dt_comp is None:
                continue
            diff = dt_comp - now
            if diff <= timedelta(0) or diff > LIMITE_12H:
                continue
            user_id = comp.get("user_id")
            if not user_id:
                continue
            user_id = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
            cliente = coll_clientes.find_one({"_id": user_id})
            if not cliente:
                continue
            telefone = cliente.get("telefone") or cliente.get("phone")
            if not telefone:
                continue
            titulo = comp.get("titulo") or comp.get("descricao") or "Compromisso"
            hora_inicio = comp.get("hora_inicio") or comp.get("hora") or ""
            data_formatada = dt_comp.strftime("%d/%m/%Y")
            codigo = str(comp["_id"])[:6]

            # Considera confirmado se flag explícita ou status confirmado (compatibilidade)
            ja_confirmado = comp.get("confirmado_usuario") or comp.get("status") == "confirmado"
            if ja_confirmado:
                # Já confirmado → enviar lembrete 12h (uma vez)
                filtro = {
                    "_id": comp["_id"],
                    "lembrete_12h_enviado": {"$ne": True},
                }
                result = coll_compromissos.update_one(
                    filtro,
                    {"$set": {"lembrete_12h_enviado": True}},
                )
                if result.modified_count == 1:
                    texto = (
                        "🔔 Lembrete!\n"
                        "Em 12 horas você tem o compromisso:\n\n"
                        f"📅 {titulo}\n"
                        f"🕒 {data_formatada} às {hora_inicio}"
                    )
                    if enviar_mensagem_waha(telefone, texto):
                        logger.info("Lembrete 12h enviado para %s — %s", telefone, titulo)
                        task_log.info(
                            "task_progress",
                            extra={
                                "event": "task_progress",
                                "trace_id": trace_id,
                                "acao": "lembrete_12h_enviado",
                                "compromisso_id": str(comp.get("_id")),
                                "user_id": str(user_id),
                            },
                        )
            else:
                # Não confirmado → enviar pedido de confirmação (uma vez)
                filtro = {
                    "_id": comp["_id"],
                    "confirmacao_enviada": {"$ne": True},
                }
                result = coll_compromissos.update_one(
                    filtro,
                    {
                        "$set": {
                            "confirmacao_enviada": True,
                            "confirmacao_pendente": True,
                            "codigo_confirmacao": codigo,
                        }
                    },
                )
                if result.modified_count == 1:
                    texto = (
                        "Você confirma este compromisso?\n\n"
                        f"📅 {titulo}\n"
                        f"🕒 {data_formatada} às {hora_inicio}\n\n"
                        "Responda:\n"
                        f"CONFIRMAR {codigo}\n"
                        "ou\n"
                        f"CANCELAR {codigo}"
                    )
                    if enviar_mensagem_waha(telefone, texto):
                        logger.info("Pedido de confirmação enviado para %s — %s", telefone, titulo)
                        task_log.info(
                            "task_progress",
                            extra={
                                "event": "task_progress",
                                "trace_id": trace_id,
                                "acao": "pedido_confirmacao_12h_enviado",
                                "compromisso_id": str(comp.get("_id")),
                                "user_id": str(user_id),
                            },
                        )
        except Exception as e:
            logger.error("Erro ao processar compromisso 12h _id=%s: %s", comp.get("_id"), e)
            _cid = None
            try:
                if comp.get("_id") is not None:
                    _cid = str(comp.get("_id"))
            except Exception:
                _cid = None
            task_log.error(
                "task_error",
                extra={
                    "event": "task_error",
                    "trace_id": trace_id,
                    "error": str(e),
                    "compromisso_id": _cid,
                },
            )

    # ----- Lembrete 1h (status confirmado) — update atômico para envio único -----
    task_log.info(
        "task_section",
        extra={
            "event": "task_section",
            "trace_id": trace_id,
            "section": "compromissos_janela_1h",
        },
    )
    cursor_1h = coll_compromissos.find({
        "status": {"$ne": "cancelado"},
        "$or": [
            {"status": "confirmado"},
            {"confirmado_usuario": True},
        ],
        "lembrete_1h_enviado": {"$ne": True},
    })
    for comp in cursor_1h:
        try:
            dt_comp = construir_datetime_compromisso(comp)
            if dt_comp is None:
                continue
            diff = dt_comp - now
            if diff <= timedelta(minutes=0) or diff > LIMITE_1H:
                continue
            user_id = comp.get("user_id")
            if not user_id:
                continue
            user_id = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
            cliente = coll_clientes.find_one({"_id": user_id})
            if not cliente:
                continue
            telefone = cliente.get("telefone") or cliente.get("phone")
            if not telefone:
                continue
            titulo = comp.get("titulo") or comp.get("descricao") or "Compromisso"
            hora_inicio = comp.get("hora_inicio") or comp.get("hora") or ""
            # Update atômico: só marca se ainda não foi marcado (evita race condition)
            result = coll_compromissos.update_one(
                {"_id": comp["_id"], "lembrete_1h_enviado": {"$ne": True}},
                {"$set": {"lembrete_1h_enviado": True}},
            )
            if result.modified_count == 1:
                texto = (
                    "🔔 Lembrete!\n"
                    "Seu compromisso começa em 1 hora:\n\n"
                    f"📅 {titulo}\n"
                    f"🕒 {hora_inicio}"
                )
                if enviar_mensagem_waha(telefone, texto):
                    logger.info("Lembrete 1h enviado para %s — %s", telefone, titulo)
                    task_log.info(
                        "task_progress",
                        extra={
                            "event": "task_progress",
                            "trace_id": trace_id,
                            "acao": "lembrete_1h_enviado",
                            "compromisso_id": str(comp.get("_id")),
                            "user_id": str(user_id),
                        },
                    )
        except Exception as e:
            logger.error("Erro ao processar compromisso 1h _id=%s: %s", comp.get("_id"), e)
            _cid = None
            try:
                if comp.get("_id") is not None:
                    _cid = str(comp.get("_id"))
            except Exception:
                _cid = None
            task_log.error(
                "task_error",
                extra={
                    "event": "task_error",
                    "trace_id": trace_id,
                    "error": str(e),
                    "compromisso_id": _cid,
                },
            )

    # ----- Despesas fixas: no máximo 1 lembrete por mês (Brasil), seguro com vários workers -----
    # Claim atômico no Mongo (ultimo_envio_mes != mês atual); rollback se WA falhar.
    logger.info("Verificando despesas fixas (dia %s)...", now.day)
    task_log.info(
        "task_section",
        extra={
            "event": "task_section",
            "trace_id": trace_id,
            "section": "despesas_fixas",
        },
    )
    try:
        filtro_mes = _filtro_nao_enviado_este_mes(now)
        cursor_df = coll_despesas_fixas.find(
            {
                "ativo": True,
                "dia_vencimento": now.day,
                **filtro_mes,
            }
        )
        for desp in cursor_df:
            antigo_ultimo = desp.get("ultimo_envio")
            antigo_mes = desp.get("ultimo_envio_mes")
            claimed = False
            try:
                agora_sp = datetime.now(TZ)
                mes_atual = _mes_atual_str(agora_sp)
                # Reserva o mês: só um worker altera (modified_count == 1)
                claim = coll_despesas_fixas.update_one(
                    {
                        "_id": desp["_id"],
                        "ativo": True,
                        "dia_vencimento": now.day,
                        **filtro_mes,
                    },
                    {
                        "$set": {
                            "ultimo_envio": agora_sp,
                            "ultimo_envio_mes": mes_atual,
                        }
                    },
                )
                if claim.modified_count != 1:
                    continue
                claimed = True

                user_id = desp.get("user_id")
                if not user_id:
                    _rollback_envio_mes(
                        coll_despesas_fixas, desp["_id"], antigo_ultimo, antigo_mes
                    )
                    continue
                user_id = (
                    ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
                )
                cliente = coll_clientes.find_one({"_id": user_id})
                if not cliente:
                    _rollback_envio_mes(
                        coll_despesas_fixas, desp["_id"], antigo_ultimo, antigo_mes
                    )
                    continue
                telefone = cliente.get("telefone") or cliente.get("phone")
                if not telefone:
                    _rollback_envio_mes(
                        coll_despesas_fixas, desp["_id"], antigo_ultimo, antigo_mes
                    )
                    continue
                nome = (desp.get("nome") or "").strip() or "despesa fixa"
                valor_fmt = _formatar_moeda_brl(desp.get("valor"))
                texto = (
                    "💸 Lembrete financeiro\n\n"
                    "Hoje é o dia de pagar:\n"
                    f"📌 {nome}\n"
                    f"💰 R$ {valor_fmt}\n\n"
                    "Não esqueça de registrar depois 😉"
                )
                if enviar_mensagem_waha(telefone, texto):
                    logger.info(
                        "Lembrete despesa fixa enviado para %s — %s",
                        telefone,
                        nome,
                    )
                    _uid_log = None
                    try:
                        _uid_log = str(user_id)
                    except Exception:
                        pass
                    task_log.info(
                        "task_progress",
                        extra={
                            "event": "task_progress",
                            "trace_id": trace_id,
                            "acao": "lembrete_despesa_fixa_enviado",
                            "despesa_id": str(desp.get("_id")),
                            "user_id": _uid_log,
                        },
                    )
                else:
                    _rollback_envio_mes(
                        coll_despesas_fixas, desp["_id"], antigo_ultimo, antigo_mes
                    )
                    logger.warning(
                        "Falha WA despesa fixa _id=%s — ultimo_envio / ultimo_envio_mes revertidos",
                        desp.get("_id"),
                    )
            except Exception as e:
                logger.error(
                    "Erro ao processar despesa fixa _id=%s: %s",
                    desp.get("_id"),
                    e,
                )
                _desp_id = None
                _uid_err = None
                try:
                    if desp.get("_id") is not None:
                        _desp_id = str(desp.get("_id"))
                except Exception:
                    pass
                try:
                    if desp.get("user_id") is not None:
                        _uid_err = str(desp.get("user_id"))
                except Exception:
                    pass
                task_log.error(
                    "task_error",
                    extra={
                        "event": "task_error",
                        "trace_id": trace_id,
                        "error": str(e),
                        "despesa_id": _desp_id,
                        "user_id": _uid_err,
                    },
                )
                if claimed:
                    try:
                        _rollback_envio_mes(
                            coll_despesas_fixas,
                            desp["_id"],
                            antigo_ultimo,
                            antigo_mes,
                        )
                    except Exception:
                        pass
    except Exception as e:
        logger.error("verificar_lembretes despesas fixas: %s", e)
        task_log.error(
            "task_error",
            extra={
                "event": "task_error",
                "trace_id": trace_id,
                "error": str(e),
            },
        )

    task_log.info(
        "task_completed",
        extra={"event": "task_completed", "trace_id": trace_id},
    )


@celery.task
def enviar_confirmacao(
    compromisso_id: str, trace_id: Optional[str] = None
) -> bool:
    """
    Envia mensagem de confirmação (lembrete 12h) para um único compromisso por ID.
    Útil para disparo sob demanda. Retorna True se enviou com sucesso.
    """
    trace_id = _resolve_trace_id(trace_id)
    task_log.info("task_start", extra={"event": "task_start", "trace_id": trace_id})
    coll_compromissos, coll_clientes, _ = get_mongo_colls()
    try:
        comp = coll_compromissos.find_one({
            "_id": ObjectId(compromisso_id),
            "status": "pendente",
            "lembrete_12h_enviado": {"$ne": True},
        })
        if not comp:
            return False
        user_id = comp.get("user_id")
        if not user_id:
            return False
        user_id = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
        cliente = coll_clientes.find_one({"_id": user_id})
        if not cliente:
            return False
        telefone = cliente.get("telefone") or cliente.get("phone")
        if not telefone:
            return False
        titulo = comp.get("titulo") or comp.get("descricao") or "Compromisso"
        hora_inicio = comp.get("hora_inicio") or comp.get("hora") or ""
        dt_comp = construir_datetime_compromisso(comp)
        data_formatada = dt_comp.strftime("%d/%m/%Y") if dt_comp else ""
        codigo = str(comp["_id"])[:6]
        texto = (
            "Você confirma este compromisso?\n\n"
            f"📅 {titulo}\n"
            f"🕒 {data_formatada} às {hora_inicio}\n\n"
            "Responda:\n"
            f"CONFIRMAR {codigo}\n"
            "ou\n"
            f"CANCELAR {codigo}"
        )
        if enviar_mensagem_waha(telefone, texto):
            coll_compromissos.update_one(
                {"_id": comp["_id"]},
                {
                    "$set": {
                        "lembrete_12h_enviado": True,
                        "confirmacao_pendente": True,
                        "codigo_confirmacao": codigo,
                    }
                },
            )
            logger.info("Lembrete 12h enviado para %s — %s (enviar_confirmacao)", telefone, titulo)
            return True
        return False
    except Exception as e:
        task_log.error(
            "task_error",
            extra={
                "event": "task_error",
                "trace_id": trace_id,
                "error": str(e),
                "compromisso_id": compromisso_id,
            },
        )
        logger.error("enviar_confirmacao compromisso_id=%s: %s", compromisso_id, e)
        return False
    finally:
        task_log.info(
            "task_completed",
            extra={"event": "task_completed", "trace_id": trace_id},
        )


@celery.task
def verificar_trial_expirado(trace_id: Optional[str] = None) -> None:
    """
    Busca usuários em trial com trial_end < agora e trial_notificado != True.
    Atualiza para sem_plano/expirado, marca trial_notificado e envia aviso no WhatsApp.
    Usa a mesma função centralizada enviar_mensagem_waha (lembretes).
    """
    trace_id = _resolve_trace_id(trace_id)
    task_log.info("task_start", extra={"event": "task_start", "trace_id": trace_id})
    _, coll_clientes, _ = get_mongo_colls()
    now = datetime.now(timezone.utc)
    # Usuários em trial com fim < agora e ainda não notificados (top-level ou assinatura)
    cursor = coll_clientes.find({
        "$and": [
            {"$or": [{"plano": "trial"}, {"assinatura.plano": "trial"}]},
            {"$or": [
                {"trial_end": {"$lt": now}},
                {"assinatura.fim": {"$lt": now}},
            ]},
            {"trial_notificado": {"$ne": True}},
        ]
    })
    for user in cursor:
        try:
            user_id = user.get("_id")
            if not user_id:
                continue
            telefone = user.get("telefone") or user.get("phone")
            if not telefone:
                logger.warning("verificar_trial_expirado: user %s sem telefone", user_id)
            else:
                texto = (
                    "⏳ Seu período de teste gratuito terminou.\n\n"
                    "Espero que você tenha aproveitado esses 7 dias para conhecer tudo que posso fazer por você 😉\n\n"
                    "Para continuar utilizando todas as funcionalidades do Leozera, escolha um dos planos disponíveis:\n\n"
                    f"👉 {LINK_PLANOS}\n\n"
                    "Se precisar de ajuda, estou aqui pra você."
                )
                if enviar_mensagem_waha(telefone, texto):
                    logger.info("Aviso trial expirado enviado para %s", telefone)
                else:
                    logger.warning("Falha ao enviar aviso trial expirado para %s", telefone)
            coll_clientes.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "plano": "sem_plano",
                        "status_pagamento": "expirado",
                        "trial_notificado": True,
                        "assinatura.plano": "sem_plano",
                        "assinatura.status": "inativa",
                        "updated_at": now,
                    }
                },
            )
            logger.info("Trial expirado processado: user_id=%s", user_id)
        except Exception as e:
            logger.error("verificar_trial_expirado: erro user_id=%s: %s", user.get("_id"), e)
    task_log.info(
        "task_completed",
        extra={"event": "task_completed", "trace_id": trace_id},
    )


@celery.task
def verificar_planos_vencidos(trace_id: Optional[str] = None) -> None:
    """
    Rebaixa automaticamente usuários cujo plano venceu.
    Considera assinatura.status em ["ativa", "cancelada"]: ambos mantêm acesso até
    assinatura.proximo_vencimento. Só após passar o vencimento o plano é encerrado
    (assinatura.plano = "sem_plano", assinatura.status = "inativa").
    """
    trace_id = _resolve_trace_id(trace_id)
    task_log.info("task_start", extra={"event": "task_start", "trace_id": trace_id})
    _, coll_clientes, _ = get_mongo_colls()
    now = datetime.now(timezone.utc)
    cursor = coll_clientes.find({
        "assinatura.status": {"$in": ["ativa", "cancelada"]},
        "assinatura.proximo_vencimento": {"$exists": True, "$lt": now},
    })
    for user in cursor:
        try:
            user_id = user.get("_id")
            if not user_id:
                continue
            coll_clientes.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "assinatura.plano": "sem_plano",
                        "assinatura.status": "inativa",
                        "downgraded_at": now,
                        "updated_at": now,
                    }
                },
            )
            logger.info("[DOWNGRADE] Usuário %s rebaixado para sem_plano", user_id)
        except Exception as e:
            logger.error("verificar_planos_vencidos: erro user_id=%s: %s", user.get("_id"), e)
    task_log.info(
        "task_completed",
        extra={"event": "task_completed", "trace_id": trace_id},
    )


@celery.task
def avaliar_resposta_task(data: dict) -> Optional[Dict[str, Any]]:
    """
    Avalia assincronamente a resposta do agente (LLM Judge).
    `data`: input_usuario, resposta_agente, trace_id; user_id opcional.
    """
    if not isinstance(data, dict):
        data = {}
    raw_tid = data.get("trace_id")
    trace_id = _resolve_trace_id(
        str(raw_tid) if raw_tid is not None else None
    )
    user_id = data.get("user_id")
    input_usuario = data.get("input_usuario") or ""
    resposta_agente = data.get("resposta_agente") or ""
    latency_ms_webhook: Optional[float] = None
    try:
        if data.get("latency_ms") is not None:
            latency_ms_webhook = float(data["latency_ms"])
    except (TypeError, ValueError):
        latency_ms_webhook = None

    start_extra: Dict[str, Any] = {
        "event": "task_start",
        "trace_id": trace_id,
    }
    if user_id is not None:
        start_extra["user_id"] = str(user_id)
    if latency_ms_webhook is not None:
        start_extra["latency_ms"] = latency_ms_webhook
    eval_log.info("task_start", extra=start_extra)

    try:
        result = avaliar_resposta(
            input_usuario=input_usuario,
            resposta_agente=resposta_agente,
            contexto=None,
        )
        result_extra: Dict[str, Any] = {
            "event": "evaluation_result",
            "trace_id": trace_id,
            "quality_score": result.get("quality_score"),
            "coherence_score": result.get("coherence_score"),
            "grounded_score": result.get("grounded_score"),
            "hallucination": result.get("hallucination"),
            "justification": result.get("justification"),
            "input_tokens": result.get("input_tokens"),
            "output_tokens": result.get("output_tokens"),
            "total_tokens": result.get("total_tokens"),
        }
        if user_id is not None:
            result_extra["user_id"] = str(user_id)
        if latency_ms_webhook is not None:
            result_extra["latency_ms"] = latency_ms_webhook
        eval_log.info("evaluation_result", extra=result_extra)
        _llm_eval_extra: Dict[str, Any] = {
            "trace_id": trace_id,
            "quality_score": result.get("quality_score"),
            "coherence_score": result.get("coherence_score"),
            "grounded_score": result.get("grounded_score"),
            "hallucination": result.get("hallucination"),
            "input_tokens": result.get("input_tokens"),
            "output_tokens": result.get("output_tokens"),
            "total_tokens": result.get("total_tokens"),
        }
        if user_id is not None:
            _llm_eval_extra["user_id"] = str(user_id)
        if latency_ms_webhook is not None:
            _llm_eval_extra["latency_ms"] = latency_ms_webhook
        logger.info("llm_evaluation", extra=_llm_eval_extra)
        try:
            coll_obs = _observabilidade_logs_coll()
            now = datetime.now(timezone.utc)
            coll_obs.insert_one(
                {
                    "event": "llm_evaluation",
                    "trace_id": trace_id,
                    "user_id": str(user_id) if user_id is not None else None,
                    "timestamp": now,
                    "input_tokens": result.get("input_tokens"),
                    "output_tokens": result.get("output_tokens"),
                    "total_tokens": result.get("total_tokens"),
                    "tokens": result.get("total_tokens"),
                    "latency_ms": latency_ms_webhook,
                    "evaluation": {
                        "quality_score": result.get("quality_score"),
                        "coherence_score": result.get("coherence_score"),
                        "grounded_score": result.get("grounded_score"),
                        "hallucination": result.get("hallucination"),
                        "justification": result.get("justification"),
                    },
                }
            )
        except Exception:
            pass
        return result
    except Exception as e:
        err_extra: Dict[str, Any] = {
            "event": "task_error",
            "trace_id": trace_id,
            "error": str(e),
        }
        if user_id is not None:
            err_extra["user_id"] = str(user_id)
        eval_log.error("task_error", extra=err_extra)
        _llm_err_extra: Dict[str, Any] = {
            "trace_id": trace_id,
            "error": str(e),
        }
        if user_id is not None:
            _llm_err_extra["user_id"] = str(user_id)
        logger.error("llm_evaluation_error", extra=_llm_err_extra)
        return None
