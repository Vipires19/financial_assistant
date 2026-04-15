"""
Logging estruturado em JSON (uma linha JSON por evento no stdout).
Compatível com processos Flask (webhooks) e workers Celery.

Uso:
    log = get_logger(__name__)
    log.info("evento", extra={"user_id": 1, "trace_id": "abc", "latency_ms": 12.3})

Variável de ambiente opcional: LOG_LEVEL (default INFO).

Para Celery, após integrar, chame configure_logging() no sinal setup_logging
do worker se o formato JSON for sobrescrito pelo Celery.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Optional, TextIO

UTC = timezone.utc

# Atributos internos do LogRecord — não são copiados como "extras" estruturados.
_LOG_RECORD_SKIP = frozenset(
    {
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "exc_info",
        "exc_text",
        "thread",
        "threadName",
        "message",
        "taskName",
    }
)

_lock = threading.Lock()
_configured = False


class JsonFormatter(logging.Formatter):
    """Emite JSON com timestamp, level, message, logger e campos extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info).strip()
        if record.stack_info:
            payload["stack_info"] = record.stack_info.strip()

        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_SKIP or key.startswith("_"):
                continue
            payload[key] = value

        return json.dumps(payload, ensure_ascii=False, default=str)


def _resolve_level() -> int:
    name = os.environ.get("LOG_LEVEL", "INFO").upper()
    return getattr(logging, name, logging.INFO)


def configure_logging(
    level: Optional[int] = None,
    *,
    stream: Optional[TextIO] = None,
) -> None:
    """
    Configura o handler JSON no root logger (idempotente).
    level: se None, usa LOG_LEVEL do ambiente ou INFO.
    """
    global _configured
    with _lock:
        root = logging.root
        if level is not None:
            root.setLevel(level)
        elif not _configured:
            root.setLevel(_resolve_level())

        for h in root.handlers:
            fmt = getattr(h, "formatter", None)
            if isinstance(fmt, JsonFormatter):
                _configured = True
                return

        handler = logging.StreamHandler(stream or sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
        _configured = True


def get_logger(name: str) -> logging.Logger:
    """Retorna um logger nomeado; garante configuração JSON na primeira utilização."""
    configure_logging()
    return logging.getLogger(name)
