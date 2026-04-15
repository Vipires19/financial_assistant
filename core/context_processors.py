"""
Context processors do app core.

Disponibilizam variáveis globais para templates (ex.: base_dashboard).
O plano do usuário vem do MongoDB (request.user_mongo), não do model User do Django.
"""

from core.services.plan_config import PLANOS
from core.services.plan_service import get_plano_recursos, usuario_tem_acesso_familia


def _precos_brl_por_chave() -> dict:
    """Valores de PLANOS formatados para exibição (ex.: 29,90)."""
    return {k: f"{float(v['valor']):.2f}".replace(".", ",") for k, v in PLANOS.items()}


def _fmt_data_br(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%d/%m/%Y")
        except Exception:
            return str(value)
    return str(value)


def plano_usuario(request):
    """
    Injeta no contexto de todos os templates:
    - plano: valor do banco (trial, mensal, anual, sem_plano)
    - data_vencimento_plano: data de vencimento para badge trial (ou None)
    - user_nome: nome do usuário (header)
    - user_profile_image: caminho da foto de perfil (header)

    Também injeta ``planos_catalogo`` e ``precos_planos_brl`` (fonte: ``plan_config.PLANOS``).
    """
    plano = 'sem_plano'
    plano_recursos = get_plano_recursos(None)
    data_vencimento_plano = None
    user_nome = None
    user_profile_image = None
    cancelamento_familia_agendado = False
    data_fim_acesso_familia = None
    data_fim_acesso_familia_fmt = ""
    acesso_familia_ativo = False

    if getattr(request, 'user_mongo', None):
        usuario = request.user_mongo
        acesso_familia_ativo = usuario_tem_acesso_familia(usuario)
        plano_recursos = get_plano_recursos(usuario)
        assinatura = usuario.get('assinatura') or {}
        plano = assinatura.get('plano') or usuario.get('plano') or 'sem_plano'
        data_vencimento_plano = (
            assinatura.get('proximo_vencimento')
            or assinatura.get('fim')
            or usuario.get('data_vencimento_plano')
        )
        user_nome = usuario.get('nome') or usuario.get('email') or 'Usuário'
        user_profile_image = usuario.get('profile_image')
        cancelamento_familia_agendado = bool(usuario.get("cancelamento_agendado"))
        data_fim_acesso_familia = usuario.get("data_fim_acesso")
        data_fim_acesso_familia_fmt = _fmt_data_br(data_fim_acesso_familia)

    return {
        'plano': plano,
        'plano_recursos': plano_recursos,
        'data_vencimento_plano': data_vencimento_plano,
        'user_nome': user_nome,
        'user_profile_image': user_profile_image,
        'cancelamento_familia_agendado': cancelamento_familia_agendado,
        'data_fim_acesso_familia': data_fim_acesso_familia,
        'data_fim_acesso_familia_fmt': data_fim_acesso_familia_fmt,
        'acesso_familia_ativo': acesso_familia_ativo,
        'planos_catalogo': PLANOS,
        'precos_planos_brl': _precos_brl_por_chave(),
    }
