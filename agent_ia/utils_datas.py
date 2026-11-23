"""
Utilitários para interpretação de datas e períodos relativos.
Usa timezone America/Sao_Paulo (Brasília).
"""
from datetime import datetime, timedelta, date
from typing import Optional, Tuple
import re

import pytz

TZ = pytz.timezone("America/Sao_Paulo")

# Mapeamento dia da semana (Python: 0=segunda, 6=domingo)
DIAS_SEMANA = {
    "segunda": 0, "segunda-feira": 0,
    "terca": 1, "terça": 1, "terca-feira": 1, "terça-feira": 1,
    "quarta": 2, "quarta-feira": 2,
    "quinta": 3, "quinta-feira": 3,
    "sexta": 4, "sexta-feira": 4,
    "sabado": 5, "sábado": 5,
    "domingo": 6,
}


def _hoje_brasilia() -> date:
    """Retorna a data de hoje no fuso de Brasília."""
    return datetime.now(TZ).date()


def resolver_periodo_relativo(periodo: str) -> Optional[Tuple[date, date]]:
    """
    Converte uma string de período relativo em intervalo concreto (data_inicio, data_fim).
    Usa timezone America/Sao_Paulo.
    
    Exemplos:
        "hoje" -> (hoje, hoje)
        "amanhã" -> (amanhã, amanhã)
        "ontem" -> (ontem, ontem)
        "próxima semana" -> (hoje, hoje+7)
        "quarta que vem" -> (próxima quarta, próxima quarta)
        "daqui 3 dias" -> (hoje+3, hoje+3)
    
    Returns:
        (data_inicio, data_fim) ou None se não reconhecer.
    """
    if not periodo or not isinstance(periodo, str):
        return None
    p = periodo.lower().strip()
    hoje = _hoje_brasilia()

    # --- Hoje ---
    if p in ("hoje", "today"):
        return (hoje, hoje)

    # --- Amanhã ---
    if p in ("amanhã", "amanha"):
        d = hoje + timedelta(days=1)
        return (d, d)

    # --- Ontem ---
    if p in ("ontem", "yesterday"):
        d = hoje - timedelta(days=1)
        return (d, d)

    # --- Daqui N dias ---
    match = re.match(r"daqui\s+(\d+)\s+dias?", p)
    if match:
        n = int(match.group(1))
        d = hoje + timedelta(days=n)
        return (d, d)

    # --- Próxima semana (hoje até hoje + 7) ---
    if "proxima semana" in p or "próxima semana" in p or "proximo semana" in p:
        fim = hoje + timedelta(days=7)
        return (hoje, fim)
    if "próximos 7 dias" in p or "proximos 7 dias" in p:
        fim = hoje + timedelta(days=7)
        return (hoje, fim)

    # --- Esta semana (hoje até domingo) ---
    if "esta semana" in p or "essa semana" in p:
        # domingo = 6; dias até domingo = (6 - weekday) % 7, se hoje for domingo = 0
        w = hoje.weekday()
        dias_ate_domingo = (6 - w) if w <= 6 else 0
        fim = hoje + timedelta(days=dias_ate_domingo)
        return (hoje, fim)

    # --- Próximo mês (hoje até +30) ---
    if "proximo mes" in p or "próximo mês" in p or "proximo mês" in p or "proximos 30 dias" in p:
        fim = hoje + timedelta(days=30)
        return (hoje, fim)

    # --- Próximos 15 dias ---
    if "15 dias" in p or "quinze dias" in p:
        fim = hoje + timedelta(days=15)
        return (hoje, fim)

    # --- Próxima segunda, terça, ... (próxima ocorrência do dia) ---
    for nome, weekday in DIAS_SEMANA.items():
        if nome in p and ("que vem" in p or "proxima" in p or "próxima" in p or "proximo" in p or "próximo" in p):
            # Próxima ocorrência desse dia da semana
            w_hoje = hoje.weekday()
            dias_ahead = (weekday - w_hoje + 7) % 7
            if dias_ahead == 0:
                dias_ahead = 7  # "próxima quarta" = semana que vem se hoje for quarta
            d = hoje + timedelta(days=dias_ahead)
            return (d, d)
        if p.strip() == nome or p.strip() == nome.replace("-feira", ""):
            # Só "sexta" ou "quarta" = próxima ocorrência
            w_hoje = hoje.weekday()
            dias_ahead = (weekday - w_hoje + 7) % 7
            if dias_ahead == 0:
                dias_ahead = 7
            d = hoje + timedelta(days=dias_ahead)
            return (d, d)

    return None


def resolver_data_relativa(periodo: str) -> Optional[date]:
    """
    Converte string de data relativa em uma única data (para criar_compromisso).
    Usa resolver_periodo_relativo e retorna a data de início do intervalo.
    """
    result = resolver_periodo_relativo(periodo)
    if result is None:
        return None
    return result[0]
