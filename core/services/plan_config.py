"""
Catálogo único de planos (preço, ciclo, tipo de recurso).

Usado por Mercado Pago, webhooks e qualquer lugar que precise do valor oficial.

Localização: core/services/plan_config.py
"""
from __future__ import annotations

from typing import Any, Dict

PLANOS: Dict[str, Dict[str, Any]] = {
    "mensal_individual": {
        "nome": "Individual Mensal",
        "valor": 29.90,
        "frequency": 1,
        "frequency_type": "months",
        "tipo_plano": "individual",
    },
    "anual_individual": {
        "nome": "Individual Anual",
        "valor": 296.90,
        "frequency": 12,
        "frequency_type": "months",
        "tipo_plano": "individual",
    },
    "mensal_familia": {
        "nome": "Família Mensal",
        "valor": 34.90,
        "frequency": 1,
        "frequency_type": "months",
        "tipo_plano": "familia",
    },
    "anual_familia": {
        "nome": "Família Anual",
        "valor": 347.90,
        "frequency": 12,
        "frequency_type": "months",
        "tipo_plano": "familia",
    },
}
