"""
URLs do app finance.

Localização: finance/urls.py

Define as rotas relacionadas a finanças.
"""
from django.urls import path
from . import views

app_name = 'finance'

urlpatterns = [
    path('', views.index_view, name='index'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('report/', views.report_view, name='report'),
    path('categorias/', views.categorias_view, name='categorias'),
    path('contas/', views.contas_view, name='contas'),
    path('transacoes/criar/', views.criar_transacao_view, name='criar-transacao'),
    path('agenda/', views.agenda_view, name='agenda'),
    path('plano/', views.plano_view, name='plano'),
    path('api/dashboard/', views.dashboard_api_view, name='dashboard-api'),
    path('api/insights/', views.insights_api_view, name='insights-api'),
    path("api/insights/", views.api_insights, name="api_insights"),
    path('api/accounts/', views.accounts_api_view, name='accounts-api'),
    path('api/accounts/balance/', views.accounts_balance_api_view, name='accounts-balance-api'),
    path('api/contas/', views.contas_list_create_api_view, name='contas-api'),
    path('api/contas/pagar-fatura/', views.pagar_fatura_api_view, name='contas-pagar-fatura'),
    path('api/contas/<str:conta_id>/', views.contas_detail_api_view, name='contas-detail-api'),
    path('api/transactions/create/', views.create_transaction_api_view, name='create-transaction-api'),
    path('api/charts/', views.charts_api_view, name='charts-api'),
    path('api/transactions/', views.transactions_api_view, name='transactions-api'),
    path('api/report/', views.report_api_view, name='report-api'),
    path('api/categorias/', views.categorias_api_view, name='categorias-api'),
    path('api/agenda/', views.agenda_api_view, name='agenda-api'),
    path('api/compromissos/create/', views.criar_compromisso_api_view, name='create-compromisso-api'),
    path('api/compromissos/<str:compromisso_id>/update/', views.atualizar_compromisso_api_view, name='update-compromisso-api'),
    path('api/compromissos/<str:compromisso_id>/delete/', views.excluir_compromisso_api_view, name='delete-compromisso-api'),
    path('api/cancelar-assinatura/', views.cancelar_assinatura_api_view, name='cancelar_assinatura_api'),
]

