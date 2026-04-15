"""
URLs da API.

Localização: api/urls.py

Centraliza todas as rotas da API REST.
"""
from django.urls import path
from core import views as core_views

urlpatterns = [
    path("planos/upgrade-familia/", core_views.upgrade_familia_api_view, name="api_upgrade_familia"),
    path("planos/assinar/", core_views.api_planos_assinar_view, name="api_planos_assinar"),
    path("planos/cancelar/", core_views.api_planos_cancelar_view, name="api_planos_cancelar"),
    path("mercadopago/webhook/", core_views.mercadopago_webhook_view, name="api_mercadopago_webhook"),
    path("user/session/", core_views.user_session_api_view, name="api_user_session"),
    path("assinar/<str:plano>/", core_views.api_assinar_plano_view, name="api_assinar_plano"),
    path("family/create/", core_views.family_create_api_view, name="api_family_create"),
    path("family/invite/", core_views.family_invite_api_view, name="api_family_invite"),
    path("family/accept/", core_views.family_accept_api_view, name="api_family_accept"),
    path("family/", core_views.family_detail_api_view, name="api_family_detail"),
]

