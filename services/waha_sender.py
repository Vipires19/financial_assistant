"""
Envio de mensagens via WAHA (WhatsApp HTTP API).
Usado pelo app (resposta do bot) e pelo worker de lembretes.
Evita duplicação e garante formato único: 55XXXXXXXXXXX@c.us (sem @lid, sem "from").
"""
import logging
import os
import re
import requests

logger = logging.getLogger(__name__)

WAHA_BASE_URL = (os.getenv("WAHA_API_URL") or "http://waha:3000").strip().rstrip("/")
WAHA_SEND_TEXT_URL = f"{WAHA_BASE_URL}/api/sendText"
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "")
WAHA_SESSION = os.getenv("WAHA_SESSION", "assistente")


def _normalizar_telefone(telefone: str) -> str:
    """
    Normaliza para formato WAHA: 55XXXXXXXXXXX@c.us.
    Apenas dígitos + 55 (Brasil). Nunca usa @lid.
    """
    if not telefone:
        return ""
    # Remove tudo que não é dígito e qualquer sufixo @c.us ou @lid
    tel = str(telefone).strip().replace("+", "").replace(" ", "")
    tel = re.sub(r"@.*$", "", tel)
    tel = re.sub(r"\D", "", tel)
    if not tel:
        return ""
    # Garante prefixo 55 (Brasil)
    if not tel.startswith("55") and len(tel) >= 10:
        tel = "55" + tel
    return f"{tel}@c.us"


def enviar_mensagem_waha(telefone: str, mensagem: str) -> bool:
    """
    Envia mensagem via WAHA sendText.
    Usa apenas telefone salvo no Mongo (normalizado para 55XXXXXXXXXXX@c.us).
    Não usa payload["from"] nem @lid.

    Args:
        telefone: Número (somente número ou com +/espaços; será normalizado).
        mensagem: Texto a enviar.

    Returns:
        True se envio OK (HTTP 200, 201 ou 202), False caso contrário.
    """
    if not telefone or not mensagem:
        logger.warning("[WAHA] enviar_mensagem_waha: telefone ou mensagem vazios")
        return False

    chat_id = _normalizar_telefone(telefone)
    if not chat_id:
        logger.warning("[WAHA] Telefone inválido após normalização: %s", telefone)
        return False

    logger.info("[WAHA] Telefone normalizado: %s -> %s", telefone, chat_id)

    payload = {
        "session": WAHA_SESSION,
        "chatId": chat_id,
        "text": mensagem,
    }

    headers = {
        "Content-Type": "application/json",
    }
    if WAHA_API_KEY:
        headers["X-Api-Key"] = WAHA_API_KEY

    try:
        r = requests.post(WAHA_SEND_TEXT_URL, json=payload, headers=headers, timeout=15)
        if r.status_code in (200, 201, 202):
            logger.info(
                "[WAHA] Mensagem enviada com sucesso: status=%s chat=%s",
                r.status_code,
                chat_id,
            )
            return True
        if r.status_code == 401:
            logger.error("[WAHA] Erro 401 Unauthorized: WAHA_API_KEY inválida ou ausente")
            return False
        if r.status_code == 404:
            logger.error("[WAHA] Erro 404 Not Found: URL ou sessão inexistente. URL=%s", WAHA_SEND_TEXT_URL)
            return False
        logger.error(
            "[WAHA] sendText falhou: status=%s body=%s",
            r.status_code,
            r.text if r.text else "",
        )
        return False
    except requests.exceptions.RequestException as e:
        logger.error("[WAHA] Erro HTTP ao enviar mensagem: %s", e)
        return False
    except Exception as e:
        logger.error("[WAHA] enviar_mensagem_waha: %s", e)
        return False
