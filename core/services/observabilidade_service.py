"""
Consultas centralizadas na collection observabilidade_logs (MongoDB).

Usa a mesma conexão que o restante do projeto (core.database.get_database).
Falhas de rede ou agregação retornam estruturas vazias / zeros — não propagam exceção.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from bson import ObjectId

from core.database import get_database

COLLECTION_NAME = "observabilidade_logs"


def _empty_metrics() -> Dict[str, Any]:
    return {
        "total_requests": 0,
        "avg_latency": 0.0,
        "total_tokens": 0,
        "total_errors": 0,
        "avg_quality_score": 0.0,
    }


def _empty_eval_summary() -> Dict[str, Any]:
    return {
        "avg_quality_score": 0.0,
        "avg_grounded_score": 0.0,
        "hallucination_rate": 0.0,
    }


def _serialize_value(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return _serialize_doc(value)
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    return value


def _serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _serialize_value(v) for k, v in doc.items()}


class ObservabilidadeService:
    """Leituras na collection observabilidade_logs."""

    def __init__(self) -> None:
        self._coll = get_database()[COLLECTION_NAME]

    def get_metrics(self) -> Dict[str, Any]:
        """
        Agrega totais e médias sobre todos os documentos da collection.

        Campos esperados (quando existirem nos documentos):
        - latency_ms (ms do invoke do agente no webhook, repassado à avaliação),
          tokens, event, status, evaluation.quality_score
        avg_latency: média apenas de valores numéricos em latency_ms (ignora ausente/null).
        """
        try:
            pipeline = [
                {
                    "$facet": {
                        "main": [
                            {
                                "$group": {
                                    "_id": None,
                                    "total_requests": {"$sum": 1},
                                    "avg_latency": {
                                        "$avg": {
                                            "$convert": {
                                                "input": "$latency_ms",
                                                "to": "double",
                                                "onError": None,
                                                "onNull": None,
                                            }
                                        }
                                    },
                                    "total_tokens": {
                                        "$sum": {
                                            "$add": [
                                                {"$ifNull": ["$tokens", 0]},
                                                {"$ifNull": ["$total_tokens", 0]},
                                            ]
                                        }
                                    },
                                    "avg_quality_score": {
                                        "$avg": "$evaluation.quality_score"
                                    },
                                }
                            }
                        ],
                        "errors": [
                            {
                                "$match": {
                                    "$or": [
                                        {
                                            "event": {
                                                "$regex": "error",
                                                "$options": "i",
                                            }
                                        },
                                        {"status": "error"},
                                    ]
                                }
                            },
                            {"$count": "total_errors"},
                        ],
                    }
                }
            ]
            rows = list(self._coll.aggregate(pipeline))
            if not rows:
                return _empty_metrics()
            facet = rows[0]
            main_list = facet.get("main") or []
            if not main_list:
                return _empty_metrics()
            m = main_list[0]
            err_list = facet.get("errors") or []
            total_errors = 0
            if err_list:
                total_errors = int(err_list[0].get("total_errors", 0))

            def _num(v: Any, default: float = 0.0) -> float:
                if v is None:
                    return default
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return default

            return {
                "total_requests": int(m.get("total_requests", 0)),
                "avg_latency": _num(m.get("avg_latency")),
                "total_tokens": int(m.get("total_tokens", 0) or 0),
                "total_errors": total_errors,
                "avg_quality_score": _num(m.get("avg_quality_score")),
            }
        except Exception:
            return _empty_metrics()

    def get_recent_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Últimos documentos ordenados por timestamp descendente."""
        try:
            lim = max(1, min(int(limit), 500))
            cursor = (
                self._coll.find()
                .sort("timestamp", -1)
                .limit(lim)
            )
            return [_serialize_doc(d) for d in cursor]
        except Exception:
            return []

    def get_costs_per_day(self) -> List[Dict[str, Any]]:
        """
        Soma tokens por dia civil (UTC) a partir de timestamp.
        tokens = tokens + total_tokens no documento (raiz).
        """
        try:
            pipeline = [
                {"$match": {"timestamp": {"$exists": True, "$ne": None}}},
                {
                    "$project": {
                        "day": {
                            "$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": "$timestamp",
                                "timezone": "UTC",
                            }
                        },
                        "tok": {
                            "$add": [
                                {"$ifNull": ["$tokens", 0]},
                                {"$ifNull": ["$total_tokens", 0]},
                            ]
                        },
                    }
                },
                {"$group": {"_id": "$day", "tokens": {"$sum": "$tok"}}},
                {"$sort": {"_id": 1}},
            ]
            out: List[Dict[str, Any]] = []
            for row in self._coll.aggregate(pipeline):
                out.append(
                    {
                        "day": row.get("_id"),
                        "tokens": int(row.get("tokens", 0) or 0),
                    }
                )
            return out
        except Exception:
            return []

    def get_evaluations_summary(self) -> Dict[str, Any]:
        """
        Médias de quality_score e grounded_score; hallucination_rate = fração
        com evaluation.hallucination verdadeiro entre documentos com evaluation.
        """
        try:
            pipeline = [
                {
                    "$match": {
                        "evaluation": {"$exists": True, "$ne": None},
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "avg_quality_score": {"$avg": "$evaluation.quality_score"},
                        "avg_grounded_score": {"$avg": "$evaluation.grounded_score"},
                        "n": {"$sum": 1},
                        "halluc_true": {
                            "$sum": {
                                "$cond": [
                                    {"$eq": ["$evaluation.hallucination", True]},
                                    1,
                                    0,
                                ]
                            }
                        },
                    }
                },
            ]
            rows = list(self._coll.aggregate(pipeline))
            if not rows:
                return _empty_eval_summary()
            r = rows[0]
            n = int(r.get("n", 0) or 0)
            halluc_true = int(r.get("halluc_true", 0) or 0)
            rate = (halluc_true / n) if n > 0 else 0.0

            def _f(v: Any) -> float:
                if v is None:
                    return 0.0
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return 0.0

            return {
                "avg_quality_score": _f(r.get("avg_quality_score")),
                "avg_grounded_score": _f(r.get("avg_grounded_score")),
                "hallucination_rate": float(rate),
            }
        except Exception:
            return _empty_eval_summary()
