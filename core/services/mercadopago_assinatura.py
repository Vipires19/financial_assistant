"""
Compatibilidade: cancelamento só no MP (use ``executar_cancelamento_pelo_usuario`` para fluxo completo).
"""
import logging

logger = logging.getLogger(__name__)


def cancelar_assinatura(mp_subscription_id: str) -> None:
    """Delega para ``mercadopago_service.cancelar_preapproval_no_mp``."""
    from core.services.mercadopago_service import cancelar_preapproval_no_mp

    cancelar_preapproval_no_mp(mp_subscription_id)
