"""
Exemplo de views para endpoints de gráficos.

Este arquivo mostra como criar endpoints API para os gráficos.
Não é um arquivo funcional, apenas exemplo.
"""
from django.http import JsonResponse
from finance.services.dashboard_service import DashboardService


def charts_category_view(request):
    """
    Endpoint para gráfico de despesas por categoria.
    
    Uso:
        GET /api/charts/category/?period=mensal
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    
    period = request.GET.get('period', 'mensal')
    
    service = DashboardService()
    data = service.get_expenses_by_category_chart_data(
        user=request.user_mongo,
        period=period
    )
    
    return JsonResponse(data, json_dumps_params={'ensure_ascii': False})


def charts_weekday_view(request):
    """
    Endpoint para gráfico de despesas por dia da semana.
    
    Uso:
        GET /api/charts/weekday/?period=mensal
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    
    period = request.GET.get('period', 'mensal')
    
    service = DashboardService()
    data = service.get_expenses_by_weekday_chart_data(
        user=request.user_mongo,
        period=period
    )
    
    return JsonResponse(data, json_dumps_params={'ensure_ascii': False})


def charts_hour_view(request):
    """
    Endpoint para gráfico de despesas por horário.
    
    Uso:
        GET /api/charts/hour/?period=mensal
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    
    period = request.GET.get('period', 'mensal')
    
    service = DashboardService()
    data = service.get_expenses_by_hour_chart_data(
        user=request.user_mongo,
        period=period
    )
    
    return JsonResponse(data, json_dumps_params={'ensure_ascii': False})


def charts_all_view(request):
    """
    Endpoint para todos os gráficos de uma vez.
    
    Uso:
        GET /api/charts/all/?period=mensal
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    
    period = request.GET.get('period', 'mensal')
    
    service = DashboardService()
    data = service.get_all_charts_data(
        user=request.user_mongo,
        period=period
    )
    
    return JsonResponse(data, json_dumps_params={'ensure_ascii': False})


# Exemplo de URLs (adicionar em finance/urls.py):
"""
from django.urls import path
from . import charts_views_example as charts_views

urlpatterns = [
    path('charts/category/', charts_views.charts_category_view, name='charts-category'),
    path('charts/weekday/', charts_views.charts_weekday_view, name='charts-weekday'),
    path('charts/hour/', charts_views.charts_hour_view, name='charts-hour'),
    path('charts/all/', charts_views.charts_all_view, name='charts-all'),
]
"""

