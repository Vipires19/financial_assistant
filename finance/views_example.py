"""
Exemplo de views usando o DashboardService.

Este arquivo mostra como integrar o DashboardService nas views.
Não é um arquivo funcional, apenas exemplo.
"""
from django.http import JsonResponse
from finance.services.dashboard_service import DashboardService


def dashboard_api_view(request):
    """
    Exemplo de view API que retorna dados do dashboard.
    
    Uso:
        GET /api/dashboard/?period=mensal
    """
    # Verifica autenticação
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    
    # Obtém período da query string (default: mensal)
    period = request.GET.get('period', 'mensal')
    
    # Valida período
    valid_periods = ['diário', 'semanal', 'mensal']
    if period not in valid_periods:
        period = 'mensal'
    
    # Gera dados do dashboard
    service = DashboardService()
    data = service.get_dashboard_data(
        user=request.user_mongo,
        period=period
    )
    
    return JsonResponse(data, json_dumps_params={'ensure_ascii': False})


def dashboard_html_view(request):
    """
    Exemplo de view que renderiza template HTML com dados do dashboard.
    
    Uso:
        GET /dashboard/?period=mensal
    """
    from django.shortcuts import render
    
    # Verifica autenticação
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        from django.shortcuts import redirect
        return redirect('core:login')
    
    # Obtém período da query string
    period = request.GET.get('period', 'mensal')
    
    # Valida período
    valid_periods = ['diário', 'semanal', 'mensal']
    if period not in valid_periods:
        period = 'mensal'
    
    # Gera dados do dashboard
    service = DashboardService()
    dashboard_data = service.get_dashboard_data(
        user=request.user_mongo,
        period=period
    )
    
    # Adiciona dados do usuário
    context = {
        'user': request.user_mongo,
        'dashboard': dashboard_data,
        'period': period,
    }
    
    return render(request, 'finance/dashboard.html', context)

