"""
Avaliação automática de respostas do agente (LLM Judge) via modelo leve.
Não propaga exceções: em qualquer falha retorna estrutura com valores padrão.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from logger import get_logger

_DEFAULT: Dict[str, Any] = {
    "quality_score": 0,
    "coherence_score": 0,
    "grounded_score": 0,
    "hallucination": True,
    "justification": "Avaliação indisponível (valores padrão).",
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
}

_eval_log = get_logger("agent_ia.evaluation")


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _extract_token_usage_from_response(resp: Any) -> Dict[str, int]:
    """
    Lê contagem de tokens de AIMessage / resposta ChatOpenAI.
    Ordem: usage_metadata → response_metadata.token_usage / usage.
    Sempre retorna input_tokens, output_tokens, total_tokens (>= 0).
    """
    inp, out, tot = 0, 0, 0
    try:
        if resp is None:
            return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        um = getattr(resp, "usage_metadata", None)
        if isinstance(um, dict) and um:
            inp = _safe_int(
                um.get("input_tokens")
                or um.get("prompt_tokens")
                or um.get("input_token_count")
            )
            out = _safe_int(
                um.get("output_tokens")
                or um.get("completion_tokens")
                or um.get("output_token_count")
            )
            tot = _safe_int(um.get("total_tokens"))
            if not tot and (inp or out):
                tot = inp + out
            return {
                "input_tokens": inp,
                "output_tokens": out,
                "total_tokens": tot,
            }

        rm = getattr(resp, "response_metadata", None)
        if isinstance(rm, dict):
            tu = rm.get("token_usage")
            if isinstance(tu, dict):
                inp = _safe_int(
                    tu.get("prompt_tokens") or tu.get("input_tokens")
                )
                out = _safe_int(
                    tu.get("completion_tokens") or tu.get("output_tokens")
                )
                tot = _safe_int(tu.get("total_tokens"))
            usage = rm.get("usage")
            if isinstance(usage, dict):
                if not inp:
                    inp = _safe_int(
                        usage.get("prompt_tokens") or usage.get("input_tokens")
                    )
                if not out:
                    out = _safe_int(
                        usage.get("completion_tokens") or usage.get("output_tokens")
                    )
                if not tot:
                    tot = _safe_int(usage.get("total_tokens"))
            if not tot and (inp or out):
                tot = inp + out
    except Exception:
        pass
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": tot,
    }

_SYSTEM_PROMPT = """Você é um avaliador imparcial da qualidade de respostas de um assistente financeiro.
Analise a entrada do usuário, a resposta do agente e o contexto fornecido (se houver).
Responda APENAS com um único objeto JSON válido, sem markdown, sem texto antes ou depois, neste formato exato:
{
  "quality_score": <inteiro de 0 a 10>,
  "coherence_score": <inteiro de 0 a 10>,
  "grounded_score": <inteiro de 0 a 10>,
  "hallucination": <true ou false>,
  "justification": "<breve justificativa em português, uma ou duas frases>"
}
Critérios:
- quality_score: utilidade, clareza e adequação ao pedido.
- coherence_score: coerência interna e fluidez.
- grounded_score: aderência ao contexto; se não houver contexto, avalie plausibilidade factual geral.
- hallucination: true se a resposta inventar fatos ou dados incompatíveis com o contexto (ou claramente incorretos quando não há contexto)."""


def _extract_json_text(raw: str) -> str:
    """Tenta isolar JSON de respostas com blocos ```json ... ``` ou texto misto."""
    if not raw or not raw.strip():
        return ""
    s = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start : end + 1].strip()
    return s


def _clamp_score(v: Any) -> int:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0
    n = int(round(x))
    return max(0, min(10, n))


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        low = v.strip().lower()
        if low in ("true", "1", "yes", "sim"):
            return True
        if low in ("false", "0", "no", "não", "nao"):
            return False
    return True


def _normalize_parsed(data: Any) -> Dict[str, Any]:
    out = dict(_DEFAULT)
    if not isinstance(data, dict):
        return out
    out["quality_score"] = _clamp_score(data.get("quality_score"))
    out["coherence_score"] = _clamp_score(data.get("coherence_score"))
    out["grounded_score"] = _clamp_score(data.get("grounded_score"))
    out["hallucination"] = _as_bool(data.get("hallucination"))
    j = data.get("justification")
    if isinstance(j, str) and j.strip():
        out["justification"] = j.strip()[:2000]
    elif j is not None:
        out["justification"] = str(j)[:2000]
    return out


def _parse_llm_json(content: str) -> Dict[str, Any]:
    try:
        blob = _extract_json_text(content)
        if not blob:
            return dict(_DEFAULT)
        data = json.loads(blob)
        return _normalize_parsed(data)
    except Exception:
        return dict(_DEFAULT)


def avaliar_resposta(
    input_usuario: str,
    resposta_agente: str,
    contexto: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Avalia a resposta do agente com um modelo leve (gpt-4o-mini).

    Retorna sempre um dict com:
      quality_score, coherence_score, grounded_score (0-10),
      hallucination (bool), justification (str).

    Em falha de API, parsing ou qualquer erro, retorna valores padrão sem lançar exceção.
    """
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return dict(_DEFAULT)

        ctx = (contexto or "").strip()
        ctx_block = (
            f"\nContexto disponível para checagem de fundamentação:\n{ctx}\n"
            if ctx
            else "\n(Nenhum contexto adicional foi fornecido; avalie plausibilidade geral.)\n"
        )

        user_block = (
            f"Pergunta ou mensagem do usuário:\n{input_usuario}\n\n"
            f"Resposta do agente:\n{resposta_agente}\n"
            f"{ctx_block}"
        )

        llm = ChatOpenAI(
            model="gpt-4o-mini",
            openai_api_key=api_key,
            temperature=0,
        )
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_block),
        ]
        resp = llm.invoke(messages)
        text = ""
        if resp is not None:
            c = getattr(resp, "content", None)
            if isinstance(c, str):
                text = c
            elif isinstance(c, list):
                parts = []
                for block in c:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                text = "".join(parts)

        parsed = _parse_llm_json(text)
        tok = _extract_token_usage_from_response(resp)
        parsed["input_tokens"] = tok["input_tokens"]
        parsed["output_tokens"] = tok["output_tokens"]
        parsed["total_tokens"] = tok["total_tokens"]
        try:
            _eval_log.info(
                "llm_token_usage",
                extra={
                    "event": "llm_token_usage",
                    "input_tokens": tok["input_tokens"],
                    "output_tokens": tok["output_tokens"],
                    "total_tokens": tok["total_tokens"],
                },
            )
        except Exception:
            pass
        return parsed
    except Exception:
        return dict(_DEFAULT)
