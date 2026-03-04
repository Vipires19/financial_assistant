"""
Serviço para cancelar assinatura no Mercado Pago (preapproval).
Usado pela página /finance/plano/ para cancelamento pelo usuário.
"""
import os
import logging
import requests

logger = logging.getLogger(__name__)

MP_PREAPPROVAL_URL = "https://api.mercadopago.com/preapproval"


def cancelar_assinatura(mp_subscription_id: str) -> None:
    """
    Cancela uma assinatura (preapproval) no Mercado Pago.
    Levanta exceção em caso de erro de rede ou resposta não sucesso.
    """
    token = os.getenv("MP_ACCESS_TOKEN")
    if not token:
        raise ValueError("MP_ACCESS_TOKEN não configurado")
    url = f"{MP_PREAPPROVAL_URL}/{mp_subscription_id}"
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
        logger.warning("MP cancelar assinatura: %s %s", r.status_code, msg)
        raise RuntimeError(msg or "Erro ao cancelar no Mercado Pago")
