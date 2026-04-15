"""
Views do app finance.

Localização: finance/views.py

Views do módulo finance. Elas chamam services para executar
a lógica de negócio e retornam respostas.
"""
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
import logging
import os
import json
import uuid
from finance.services.transaction_service import TransactionService
from core.repositories.user_repository import UserRepository
from finance.services.dashboard_service import DashboardService
from finance.services.compromisso_service import CompromissoService
from core.services.categoria_usuario_service import CategoriaUsuarioService
from finance.models.categoria_model import CategoriaModel
from finance.models import FinancialAccount
from django.contrib.auth import get_user_model
from core.decorators import audit_log
from core.decorators.auth import login_required_mongo
from finance.repositories.despesa_fixa_repository import DespesaFixaRepository
from core.services.user_scope import resolve_user_read_scope
from core.services.family_ui_service import member_id_to_display_names
from datetime import datetime, timedelta
from dotenv import load_dotenv,find_dotenv
load_dotenv(find_dotenv())


logger = logging.getLogger(__name__)


def index_view(request):
    """View principal do finance."""
    return JsonResponse({
        'message': 'Finance API',
        'status': 'ok'
    })


@login_required_mongo
def dashboard_view(request):
    """
    View do dashboard financeiro (HTML).
    
    Requer autenticação via sessão.
    """
    return render(request, 'finance/dashboard.html', {
        'user': request.user_mongo if hasattr(request, 'user_mongo') and request.user_mongo else None
    })


def dashboard_api_view(request):
    """
    API endpoint para dados do dashboard.
    
    GET /api/finance/dashboard/?period=mensal
    
    SEGURANÇA: user_id é extraído do request.user_mongo (garantido pelo middleware).
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    
    period = request.GET.get('period', 'mensal')
    month = request.GET.get('month')
    year = request.GET.get('year')
    if month is not None and month != '':
        try:
            month = int(month)
        except (ValueError, TypeError):
            month = None
    else:
        month = None
    if year is not None and year != '':
        try:
            year = int(year)
        except (ValueError, TypeError):
            year = None
    else:
        year = None

    service = DashboardService()
    data = service.get_dashboard_data(
        user=request.user_mongo,
        period=period,
        month=month,
        year=year
    )
    
    return JsonResponse(data, json_dumps_params={'ensure_ascii': False})


def insights_api_view(request):
    """
    API endpoint para insights financeiros gerados por IA (modelo híbrido).

    GET /finance/api/insights/?period=mensal|geral|...

    Obtém dados do dashboard, envia para o serviço de insights (que calcula padrões
    no backend e usa a IA só para interpretar). Com period=geral, a janela é longa (~24 meses)
    e o prompt foca comportamento e hábitos (não “este mês”).
    SEGURANÇA: user_id é extraído do request.user_mongo (garantido pelo middleware).
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)

    period = request.GET.get('period', 'mensal')

    def _q_int(name):
        raw = request.GET.get(name)
        if raw is None or raw == '':
            return None
        try:
            return int(raw)
        except (ValueError, TypeError):
            return None

    month = _q_int('month')
    year = _q_int('year')

    try:
        service = DashboardService()
        dashboard_data = service.get_dashboard_data(
            user=request.user_mongo, period=period, month=month, year=year
        )
    except Exception as e:
        logger.exception("Erro ao obter dados do dashboard para insights: %s", e)
        return JsonResponse({
            'error': 'Erro ao carregar dados',
            'message': str(e)
        }, status=500)

    def _serialize_for_insights(obj):
        if obj is None:
            return None
        if isinstance(obj, (int, float, str, bool)):
            return obj
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: _serialize_for_insights(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_serialize_for_insights(v) for v in obj]
        return str(obj)

    # Montar payload para o serviço de insights (com transações e contas para cálculos)
    transactions = dashboard_data.get('transactions') or []
    transactions_serial = [
        {
            'type': t.get('type'),
            'value': t.get('value'),
            'account_id': str(t['account_id']) if t.get('account_id') is not None else None,
        }
        for t in transactions
    ]
    accounts = dashboard_data.get('accounts') or []
    accounts_serial = [
        {'id': str(a.get('id') or a.get('_id', '')), 'name': a.get('name') or a.get('nome', '')}
        for a in accounts
    ]
    category_highest = dashboard_data.get('category_with_highest_expense')
    if category_highest and isinstance(category_highest, dict):
        category_highest = _serialize_for_insights(category_highest)

    total_exp = float(dashboard_data.get('total_expenses') or 0)
    top_cats_raw = dashboard_data.get('top_expense_categories') or []
    top_expense_categories_serial = []
    for c in top_cats_raw:
        if not isinstance(c, dict):
            continue
        cat_total = float(c.get('total') or 0)
        top_expense_categories_serial.append({
            'category': c.get('category'),
            'total': cat_total,
            'percentual_sobre_despesas': round(cat_total / total_exp, 4) if total_exp else 0.0,
        })

    period_norm = (period or '').strip().lower()
    insight_modo = 'geral' if period_norm == 'geral' else 'periodo'

    payload = {
        'total_income': dashboard_data.get('total_income', 0),
        'total_expenses': dashboard_data.get('total_expenses', 0),
        'balance': dashboard_data.get('balance', 0),
        'day_with_highest_expense': _serialize_for_insights(dashboard_data.get('day_with_highest_expense')),
        'category_with_highest_expense': category_highest,
        'hour_with_highest_expense': _serialize_for_insights(dashboard_data.get('hour_with_highest_expense')),
        'transactions': transactions_serial,
        'accounts': accounts_serial,
        'insight_modo': insight_modo,
        'top_expense_categories': top_expense_categories_serial,
    }

    from .services.ai_insights import gerar_insights_financeiros
    insights = gerar_insights_financeiros(payload)
    return JsonResponse(insights, json_dumps_params={'ensure_ascii': False})


@login_required_mongo
def charts_api_view(request):
    """
    API endpoint para dados de gráficos.
    
    GET /api/finance/charts/?type=all&period=mensal
    
    SEGURANÇA: user_id é extraído do request.user_mongo (garantido pelo middleware).
    """
    # Verificação adicional de segurança
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({
            'error': 'Não autenticado',
            'message': 'É necessário fazer login para acessar os gráficos'
        }, status=401)
    
    period = request.GET.get('period', 'mensal')
    month = request.GET.get('month')
    year = request.GET.get('year')
    month = int(month) if month else None
    year = int(year) if year else None
    chart_type = request.GET.get('type', 'all')

    try:
        service = DashboardService()
        um = request.user_mongo
        
        if chart_type == 'category':
            data = service.get_expenses_by_category_chart_data(um, period, month, year)
        elif chart_type == 'weekday':
            data = service.get_expenses_by_weekday_chart_data(um, period, month, year)
        elif chart_type == 'hour':
            data = service.get_expenses_by_hour_chart_data(um, period, month, year)
        else:  # 'all'
            data = service.get_all_charts_data(
                user=um,
                period=period,
                month=month,
                year=year
            )
        
        return JsonResponse(data, json_dumps_params={'ensure_ascii': False})
    
    except ValueError as e:
        return JsonResponse({
            'error': 'Erro ao buscar dados dos gráficos',
            'message': str(e)
        }, status=400)
    except Exception as e:
        import traceback
        return JsonResponse({
            'error': 'Erro interno do servidor',
            'message': str(e),
            'traceback': traceback.format_exc() if request.GET.get('debug') == 'true' else None
        }, status=500)


def transactions_api_view(request):
    """
    API endpoint para lista de transações com paginação.
    
    GET /finance/api/transactions/?period=mensal&page=1&limit=20
    
    SEGURANÇA: user_id é extraído do request.user_mongo (garantido pelo middleware).
    Nenhum usuário pode acessar transações de outro usuário.
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    
    period = request.GET.get('period', 'mensal')
    page = int(request.GET.get('page', 1))
    limit = int(request.GET.get('limit', 20))
    
    # Validações
    if page < 1:
        page = 1
    if limit < 1 or limit > 100:
        limit = 20
    
    skip = (page - 1) * limit
    
    service = DashboardService()
    start_date, end_date = service._get_period_dates(period)
    scope, _ = resolve_user_read_scope(request.user_mongo)
    
    raw = service._get_filtered_transactions(
        scope,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        skip=skip,
        viewer=request.user_mongo,
    )
    pag = raw.get("pagination") or {}
    payload = {
        "transactions": raw.get("transactions", []),
        **pag,
    }
    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False})


def report_api_view(request):
    """
    API endpoint para geração de relatórios.
    
    GET /finance/api/report/?period=mensal&format=text&use_ai=false
    
    SEGURANÇA: user_id é extraído do request.user_mongo (garantido pelo middleware).
    Relatórios sempre gerados apenas com dados do usuário autenticado.
    
    Parâmetros:
    - period: 'diário', 'semanal', 'mensal'
    - format: 'text', 'json' (futuro: 'pdf')
    - use_ai: 'true' ou 'false' (futuro: análise com IA)
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    
    period = request.GET.get('period', 'mensal')
    format_type = request.GET.get('format', 'text')
    use_ai = request.GET.get('use_ai', 'false').lower() == 'true'
    
    # Validações
    valid_periods = ['diário', 'semanal', 'mensal']
    if period not in valid_periods:
        period = 'mensal'
    
    valid_formats = ['text', 'json', 'pdf']
    if format_type not in valid_formats:
        format_type = 'text'
    
    from finance.services.report_service import ReportService
    report_service = ReportService()
    
    try:
        if format_type == 'pdf':
            # Por enquanto, retorna erro (não implementado)
            return JsonResponse({
                'error': 'Geração de PDF ainda não implementada',
                'available_formats': ['text', 'json']
            }, status=501)
        
        report = report_service.generate_report(
            user=request.user_mongo,
            period=period,
            format=format_type,
            use_ai=use_ai
        )
        
        return JsonResponse(report, json_dumps_params={'ensure_ascii': False})
    
    except Exception as e:
        return JsonResponse({
            'error': 'Erro ao gerar relatório',
            'message': str(e)
        }, status=500)


def report_view(request):
    """
    View HTML para exibir relatório em página simples.
    
    GET /finance/report/?period=mensal
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        from django.shortcuts import redirect
        return redirect('core:login')
    
    period = request.GET.get('period', 'mensal')
    
    from finance.services.report_service import ReportService
    report_service = ReportService()
    
    try:
        report_data = report_service.generate_text_report(
            user=request.user_mongo,
            period=period
        )
        
        return render(request, 'finance/report.html', {
            'user': request.user_mongo,
            'report_text': report_data['report_text'],
            'metadata': report_data['metadata'],
            'summary': report_data['summary']
        })
    
    except Exception as e:
        from django.contrib import messages
        messages.error(request, f'Erro ao gerar relatório: {str(e)}')
        from django.shortcuts import redirect
        return redirect('finance:dashboard')


@login_required_mongo
def categorias_view(request):
    """
    View para gerenciar categorias personalizadas.
    
    GET: Exibe lista de categorias e formulário para adicionar
    POST: Cria nova categoria
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return redirect('/login/')
    
    user_id = str(request.user_mongo['_id'])
    categoria_service = CategoriaUsuarioService()
    
    if request.method == 'POST':
        action = request.POST.get('action', 'add')
        
        if action == 'add':
            nome = request.POST.get('nome', '').strip()
            tipo = request.POST.get('tipo', '').strip()
            
            try:
                categoria_service.adicionar_categoria(user_id, tipo, nome)
                messages.success(request, f'Categoria "{nome}" adicionada com sucesso!')
            except ValueError as e:
                messages.error(request, str(e))
        
        elif action == 'remove':
            nome = request.POST.get('nome', '').strip()
            tipo = request.POST.get('tipo', '').strip()
            
            try:
                categoria_service.remover_categoria(user_id, tipo, nome)
                messages.success(request, f'Categoria "{nome}" removida com sucesso!')
            except ValueError as e:
                messages.error(request, str(e))
        
        elif action == 'edit':
            nome_antigo = request.POST.get('nome_antigo', '').strip()
            nome_novo = request.POST.get('nome_novo', '').strip()
            tipo = request.POST.get('tipo', '').strip()
            
            try:
                categoria_service.editar_categoria(user_id, tipo, nome_antigo, nome_novo)
                messages.success(request, f'Categoria atualizada com sucesso!')
            except ValueError as e:
                messages.error(request, str(e))
        
        return redirect('finance:categorias')
    
    # Busca categorias do usuário
    categorias_por_tipo = categoria_service.get_categorias_usuario(user_id)
    tipos_disponiveis = CategoriaModel.TIPOS
    
    return render(request, 'finance/categorias.html', {
        'user': request.user_mongo,
        'categorias_por_tipo': categorias_por_tipo,
        'tipos_disponiveis': tipos_disponiveis
    })


def _parse_valor_br(val: str) -> float:
    """Converte string de valor (pt-BR ou número com ponto) em float."""
    s = (val or "").strip()
    if not s:
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def _fmt_brl(val) -> str:
    try:
        v = float(val)
    except (TypeError, ValueError):
        v = 0.0
    neg = v < 0
    v = abs(v)
    s = f"{v:.2f}"
    intp, frac = s.split(".")
    parts = []
    while intp:
        parts.insert(0, intp[-3:])
        intp = intp[:-3]
    int_fmt = ".".join(parts)
    prefix = "-" if neg else ""
    return f"{prefix}R$ {int_fmt},{frac}"


@login_required_mongo
def despesas_fixas_view(request):
    """Lista e CRUD de despesas fixas (recorrentes) do usuário."""
    if not hasattr(request, "user_mongo") or not request.user_mongo:
        return redirect("/login/")

    user_id = str(request.user_mongo["_id"])
    repo = DespesaFixaRepository()

    if request.method == "POST":
        action = request.POST.get("action", "add")
        if action == "add":
            try:
                dia = int(request.POST.get("dia_vencimento", "1"))
            except (TypeError, ValueError):
                messages.error(request, "Dia de vencimento inválido.")
                return redirect("finance:despesas-fixas")
            try:
                valor_parsed = _parse_valor_br(request.POST.get("valor", "0"))
            except ValueError:
                messages.error(request, "Valor inválido.")
                return redirect("finance:despesas-fixas")
            try:
                repo.create(
                    {
                        "user_id": user_id,
                        "nome": request.POST.get("nome", ""),
                        "valor": valor_parsed,
                        "dia_vencimento": dia,
                    }
                )
                messages.success(request, "Despesa fixa adicionada com sucesso!")
            except ValueError as e:
                messages.error(request, str(e))
        elif action == "edit":
            despesa_id = request.POST.get("despesa_id", "").strip()
            try:
                dia = int(request.POST.get("dia_vencimento", "1"))
            except (TypeError, ValueError):
                messages.error(request, "Dia de vencimento inválido.")
                return redirect("finance:despesas-fixas")
            try:
                valor_parsed = _parse_valor_br(request.POST.get("valor", "0"))
            except ValueError:
                messages.error(request, "Valor inválido.")
                return redirect("finance:despesas-fixas")
            try:
                ok = repo.update_by_user(
                    despesa_id,
                    user_id,
                    nome=request.POST.get("nome", ""),
                    valor=valor_parsed,
                    dia_vencimento=dia,
                )
                if ok:
                    messages.success(request, "Despesa fixa atualizada com sucesso!")
                else:
                    messages.error(
                        request, "Registro não encontrado ou sem permissão."
                    )
            except ValueError as e:
                messages.error(request, str(e))
        elif action == "remove":
            despesa_id = request.POST.get("despesa_id", "").strip()
            if repo.delete_by_user(despesa_id, user_id):
                messages.success(request, "Despesa fixa removida com sucesso!")
            else:
                messages.error(request, "Não foi possível remover.")
        return redirect("finance:despesas-fixas")

    docs = repo.find_for_read_scope(request.user_mongo, apenas_ativas=False)
    _, member_ids = resolve_user_read_scope(request.user_mongo)
    owner_labels = member_id_to_display_names(member_ids)
    self_uid = str(request.user_mongo["_id"])
    has_family = bool(request.user_mongo.get("family_group_id"))

    despesas = []
    for d in docs:
        v = d.get("valor", 0)
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.0
        oid = str(d.get("user_id", ""))
        despesas.append(
            {
                "id": str(d["_id"]),
                "nome": d.get("nome", ""),
                "valor": v,
                "valor_display": _fmt_brl(v),
                "dia_vencimento": int(d.get("dia_vencimento", 1)),
                "ativo": d.get("ativo", True),
                "owner_nome": owner_labels.get(oid, "Membro"),
                "is_mine": oid == self_uid,
            }
        )

    return render(
        request,
        "finance/despesas_fixas.html",
        {
            "user": request.user_mongo,
            "despesas": despesas,
            "dias_vencimento": list(range(1, 32)),
            "has_family": has_family,
        },
    )


@login_required_mongo
def categorias_api_view(request):
    """
    API endpoint para buscar categorias do usuário.
    
    GET /finance/api/categorias/?tipo=receita
    
    SEGURANÇA: Requer autenticação via sessão. Apenas usuários autenticados
    podem acessar suas próprias categorias.
    """
    # Verificação adicional de segurança
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({
            'error': 'Não autenticado',
            'message': 'É necessário fazer login para acessar as categorias'
        }, status=401)
    
    # Obtém o ID do usuário autenticado (garantido pelo middleware e decorator)
    user_id = str(request.user_mongo['_id'])
    tipo = request.GET.get('tipo', None)
    
    try:
        categoria_service = CategoriaUsuarioService()
        
        if tipo:
            # Retorna apenas categorias do tipo especificado
            categorias = categoria_service.get_categorias_por_tipo(user_id, tipo)
            categorias_formatted = [{'nome': nome, 'tipo': tipo} for nome in categorias]
        else:
            # Retorna todas as categorias formatadas
            categorias_formatted = categoria_service.get_todas_categorias_formatadas(user_id)
        
        return JsonResponse({
            'categorias': categorias_formatted,
            'user_id': user_id  # Para debug (pode remover em produção)
        }, json_dumps_params={'ensure_ascii': False})
    
    except ValueError as e:
        return JsonResponse({
            'error': 'Erro ao buscar categorias',
            'message': str(e)
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'error': 'Erro interno do servidor',
            'message': str(e)
        }, status=500)

@login_required_mongo
def contas_view(request):
    """Página de gerenciamento de contas financeiras (listar, criar, editar, desativar)."""
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return redirect('/login/')
    return render(request, 'finance/contas.html', {'user': request.user_mongo})


@login_required_mongo
def criar_transacao_view(request):
    """
    View para criar nova transação.
    
    GET: Exibe formulário
    POST: Cria transação
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return redirect('/login/')
    
    user_id = str(request.user_mongo['_id'])
    categoria_service = CategoriaUsuarioService()
    
    # Busca todas as categorias do usuário para o formulário
    todas_categorias = categoria_service.get_todas_categorias_formatadas(user_id)
    
    return render(request, 'finance/criar_transacao.html', {
        'user': request.user_mongo,
        'categorias': todas_categorias
    })


def accounts_api_view(request):
    """
    API endpoint para listar contas financeiras do usuário.
    
    GET /finance/api/accounts/
    Retorna lista de contas ativas para o usuário autenticado (Django User por email).
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    if request.method != 'GET':
        return JsonResponse({'error': 'Método não permitido'}, status=405)
    email = request.user_mongo.get('email')
    if not email:
        return JsonResponse([], safe=False)
    User = get_user_model()
    django_user = User.objects.filter(email=email.lower()).first()
    if not django_user:
        return JsonResponse([], safe=False)
    accounts = FinancialAccount.objects.filter(user=django_user, is_active=True).order_by('name')
    data = [{'id': str(acc.id), 'name': acc.name, 'type': acc.type} for acc in accounts]
    return JsonResponse(data, safe=False)


def accounts_balance_api_view(request):
    """
    GET /finance/api/accounts/balance/
    Retorna saldo total e saldo por conta (user.contas + transações).
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    if request.method != 'GET':
        return JsonResponse({'error': 'Método não permitido'}, status=405)
    service = DashboardService()
    data = service.get_account_balances(request.user_mongo)
    return JsonResponse({
        'total_balance': data['total_balance'],
        'accounts': data['accounts'],
        'credit_cards': data.get('credit_cards', []),
    }, json_dumps_params={'ensure_ascii': False})


def contas_list_create_api_view(request):
    """
    GET /finance/api/contas/ — lista contas do usuário (user.contas no MongoDB).
    POST /finance/api/contas/ — cria nova conta em user.contas.
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)

    user_id = str(request.user_mongo['_id'])
    user_repo = UserRepository()
    user = user_repo.find_by_id(user_id)
    if not user:
        return JsonResponse({'error': 'Usuário não encontrado'}, status=404)

    contas = user.get('contas') or []

    if request.method == 'GET':
        return JsonResponse({'contas': contas}, json_dumps_params={'ensure_ascii': False})

    if request.method == 'POST':
        try:
            if request.content_type and 'application/json' in request.content_type:
                data = json.loads(request.body)
            else:
                data = request.POST.dict()
            nome = (data.get('nome') or '').strip()
            tipo = (data.get('tipo') or 'other').strip()
            saldo_inicial = float(data.get('saldo_inicial', 0))
        except (json.JSONDecodeError, ValueError, TypeError):
            return JsonResponse({'error': 'Payload inválido'}, status=400)
        if not nome:
            return JsonResponse({'error': 'nome é obrigatório'}, status=400)
        nova_conta = {
            'id': str(uuid.uuid4()),
            'nome': nome,
            'tipo': tipo,
            'saldo_inicial': saldo_inicial,
            'ativa': True,
        }
        contas.append(nova_conta)
        if not user_repo.update(user_id, contas=contas):
            return JsonResponse({'error': 'Erro ao salvar conta'}, status=500)
        return JsonResponse({'contas': contas, 'conta': nova_conta}, json_dumps_params={'ensure_ascii': False}, status=201)

    return JsonResponse({'error': 'Método não permitido'}, status=405)


def pagar_fatura_api_view(request):
    """
    POST /finance/api/contas/pagar-fatura/
    Payload: { "cartao_id": "...", "conta_pagadora_id": "...", "valor": 1000 }
    Cria expense na conta pagadora e income no cartão; retorna sucesso e saldos atualizados.
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido'}, status=405)

    user_id = str(request.user_mongo['_id'])
    try:
        if request.content_type and 'application/json' in request.content_type:
            data = json.loads(request.body)
        else:
            data = request.POST.dict()
        cartao_id = (data.get('cartao_id') or '').strip()
        conta_pagadora_id = (data.get('conta_pagadora_id') or '').strip()
        valor = float(data.get('valor', 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({'error': 'Payload inválido. Envie cartao_id, conta_pagadora_id e valor.'}, status=400)

    if not cartao_id or not conta_pagadora_id:
        return JsonResponse({'error': 'cartao_id e conta_pagadora_id são obrigatórios'}, status=400)
    if valor <= 0:
        return JsonResponse({'error': 'valor deve ser maior que zero'}, status=400)

    user_repo = UserRepository()
    user = user_repo.find_by_id(user_id)
    if not user:
        return JsonResponse({'error': 'Usuário não encontrado'}, status=404)

    contas = user.get('contas') or []
    cartao = next((c for c in contas if c.get('id') == cartao_id), None)
    conta_pagadora = next((c for c in contas if c.get('id') == conta_pagadora_id), None)

    if not cartao:
        return JsonResponse({'error': 'Cartão não encontrado'}, status=404)
    if cartao.get('tipo') != 'credit_card':
        return JsonResponse({'error': 'cartao_id deve ser uma conta do tipo credit_card'}, status=400)

    if not conta_pagadora:
        return JsonResponse({'error': 'Conta pagadora não encontrada'}, status=404)
    if conta_pagadora.get('tipo') == 'credit_card':
        return JsonResponse({'error': 'conta_pagadora_id não pode ser um cartão de crédito'}, status=400)

    transaction_service = TransactionService()
    now = datetime.utcnow()

    try:
        trans_saida = transaction_service.create_transaction(
            user_id=user_id,
            amount=valor,
            description='Pagamento fatura cartão de crédito',
            transaction_type='expense',
            category='outros',
            account_id=conta_pagadora_id,
            created_at=now,
        )
        trans_entrada = transaction_service.create_transaction(
            user_id=user_id,
            amount=valor,
            description='Pagamento fatura (entrada no cartão)',
            transaction_type='income',
            category='outros',
            account_id=cartao_id,
            created_at=now,
        )
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    service = DashboardService()
    balances = service.get_account_balances(request.user_mongo)
    return JsonResponse({
        'success': True,
        'message': 'Fatura paga com sucesso.',
        'total_balance': balances['total_balance'],
        'accounts': balances['accounts'],
        'credit_cards': balances.get('credit_cards', []),
    }, json_dumps_params={'ensure_ascii': False})


def contas_detail_api_view(request, conta_id):
    """
    PUT /finance/api/contas/<id>/ — edita nome, tipo, saldo_inicial (não altera id).
    DELETE /finance/api/contas/<id>/ — desativa conta (ativa=False). Não permite desativar conta_principal.
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)

    if request.method == 'DELETE':
        if conta_id == 'conta_principal':
            return JsonResponse({'error': 'Não é permitido desativar a Conta Principal'}, status=400)
        user_id = str(request.user_mongo['_id'])
        user_repo = UserRepository()
        user = user_repo.find_by_id(user_id)
        if not user:
            return JsonResponse({'error': 'Usuário não encontrado'}, status=404)
        contas = user.get('contas') or []
        encontrada = False
        for conta in contas:
            if conta.get('id') == conta_id:
                conta['ativa'] = False
                encontrada = True
                break
        if not encontrada:
            return JsonResponse({'error': 'Conta não encontrada'}, status=404)
        if not user_repo.update(user_id, contas=contas):
            return JsonResponse({'error': 'Erro ao atualizar conta'}, status=500)
        return JsonResponse({'contas': contas}, json_dumps_params={'ensure_ascii': False})

    if request.method == 'PUT':
        user_id = str(request.user_mongo['_id'])
        user_repo = UserRepository()
        user = user_repo.find_by_id(user_id)
        if not user:
            return JsonResponse({'error': 'Usuário não encontrado'}, status=404)
        try:
            if request.content_type and 'application/json' in request.content_type:
                data = json.loads(request.body)
            else:
                data = request.POST.dict()
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Payload inválido'}, status=400)
        contas = user.get('contas') or []
        encontrada = False
        for conta in contas:
            if conta.get('id') == conta_id:
                if 'nome' in data and data['nome'] is not None:
                    conta['nome'] = str(data['nome']).strip()
                if 'tipo' in data and data['tipo'] is not None:
                    conta['tipo'] = str(data['tipo']).strip()
                if 'saldo_inicial' in data and data['saldo_inicial'] is not None:
                    try:
                        conta['saldo_inicial'] = float(data['saldo_inicial'])
                    except (ValueError, TypeError):
                        pass
                encontrada = True
                break
        if not encontrada:
            return JsonResponse({'error': 'Conta não encontrada'}, status=404)
        if not user_repo.update(user_id, contas=contas):
            return JsonResponse({'error': 'Erro ao atualizar conta'}, status=500)
        return JsonResponse({'contas': contas}, json_dumps_params={'ensure_ascii': False})

    return JsonResponse({'error': 'Método não permitido'}, status=405)


def create_transaction_api_view(request):
    """
    API endpoint para criar transação.
    
    POST /finance/api/transactions/create/
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido'}, status=405)
    
    user_id = str(request.user_mongo['_id'])
    
    try:
        import json
        from datetime import datetime
        
        # Tenta ler JSON primeiro, depois FormData
        if request.content_type and 'application/json' in request.content_type:
            try:
                data = json.loads(request.body)
                transaction_type = data.get('tipo')
                categoria = data.get('categoria')
                valor = data.get('valor')
                descricao = data.get('descricao')
                data_str = data.get('data')  # Pode ser 'YYYY-MM-DD' ou 'YYYY-MM-DDTHH:MM:SS'
                account_id = data.get('account_id')
            except:
                transaction_type = None
                categoria = None
                valor = None
                descricao = None
                data_str = None
                account_id = None
        else:
            transaction_type = request.POST.get('tipo')
            categoria = request.POST.get('categoria')
            valor = request.POST.get('valor')
            descricao = request.POST.get('descricao')
            data_str = request.POST.get('data')
            account_id = request.POST.get('account_id') or None
        
        if not all([transaction_type, categoria, valor, descricao]):
            return JsonResponse({'error': 'Campos obrigatórios: tipo, categoria, valor, descricao'}, status=400)
        
        # Valida categoria do usuário
        categoria_service = CategoriaUsuarioService()
        categorias_usuario = categoria_service.get_categorias_usuario(user_id)
        
        # Verifica se categoria existe nas categorias do usuário
        categoria_valida = False
        for tipo_cat, nomes in categorias_usuario.items():
            if categoria in nomes:
                categoria_valida = True
                break
        
        if not categoria_valida:
            return JsonResponse({'error': 'Categoria inválida ou não pertence ao usuário'}, status=400)
        
        # Cria transação
        transaction_service = TransactionService()
        
        # Converte data_str para datetime se fornecido
        # Aceita formatos: 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM:SS', 'YYYY-MM-DDTHH:MM'
        created_at = None
        if data_str:
            try:
                # Tenta formato ISO completo primeiro
                if 'T' in data_str:
                    if len(data_str) == 16:  # 'YYYY-MM-DDTHH:MM'
                        created_at = datetime.strptime(data_str, '%Y-%m-%dT%H:%M')
                    else:  # 'YYYY-MM-DDTHH:MM:SS' ou 'YYYY-MM-DDTHH:MM:SSZ'
                        created_at = datetime.fromisoformat(data_str.replace('Z', '+00:00'))
                else:
                    # Apenas data, usa hora atual
                    created_at = datetime.strptime(data_str, '%Y-%m-%d')
            except Exception as e:
                # Se falhar, usa data/hora atual
                created_at = None
        
        transaction = transaction_service.create_transaction(
            user_id=user_id,
            amount=float(valor),
            description=descricao,
            transaction_type=transaction_type,
            category=categoria,
            created_at=created_at,
            account_id=account_id if account_id else None
        )
        
        return JsonResponse({
            'success': True,
            'transaction': {
                'id': str(transaction['_id']),
                'type': transaction['type'],
                'category': transaction['category'],
                'description': transaction['description'],
                'value': transaction['value']
            }
        }, json_dumps_params={'ensure_ascii': False})
    
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Erro ao criar transação: {str(e)}'}, status=500)


# ========================================
# AGENDA / COMPROMISSOS
# ========================================

@login_required_mongo
def agenda_view(request):
    """
    View da página de agenda.
    
    Requer autenticação via sessão.
    """
    return render(request, 'finance/agenda.html', {
        'user': request.user_mongo if hasattr(request, 'user_mongo') and request.user_mongo else None
    })


@login_required_mongo
def plano_view(request):
    """
    View da página de gerenciamento de plano do usuário.
    Lê apenas de user["assinatura"]: plano, status, proximo_vencimento.
    Não usa campos antigos (status_pagamento, data_vencimento_plano).
    """
    user = request.user_mongo
    assinatura = user.get("assinatura", {})

    plano = assinatura.get("plano")
    plano_key = assinatura.get("plano_key") or assinatura.get("plano_solicitado")
    status = assinatura.get("status")
    proximo_vencimento = assinatura.get("proximo_vencimento")

    tipo_plano = (user.get("tipo_plano") or "").strip().lower()
    if tipo_plano not in ("individual", "familia"):
        if isinstance(plano_key, str) and plano_key.endswith("_familia"):
            tipo_plano = "familia"
        elif isinstance(plano_key, str) and plano_key.endswith("_individual"):
            tipo_plano = "individual"
        elif isinstance(plano, str):
            if "familia" in plano:
                tipo_plano = "familia"
            elif "individual" in plano:
                tipo_plano = "individual"

    tipo_plano_label = "—"
    if tipo_plano == "familia":
        tipo_plano_label = "Família"
    elif tipo_plano == "individual":
        tipo_plano_label = "Individual"

    proximo_vencimento_str = None
    if proximo_vencimento and hasattr(proximo_vencimento, "strftime"):
        proximo_vencimento_str = proximo_vencimento.strftime("%d/%m/%Y")
    elif proximo_vencimento is not None:
        proximo_vencimento_str = str(proximo_vencimento)

    context = {
        "plano": plano,
        "plano_key": plano_key,
        "tipo_plano_label": tipo_plano_label,
        "status": status,
        "proximo_vencimento": proximo_vencimento_str,
    }
    return render(request, "finance/plano.html", context)


@login_required_mongo
@require_POST
def cancelar_assinatura_api_view(request):
    """
    Cancela a assinatura do usuário no Mercado Pago e atualiza o MongoDB (plano sem_plano, status inativa).
    """
    user = request.user_mongo
    assinatura = user.get("assinatura", {})
    try:
        from core.services.mercadopago_service import executar_cancelamento_pelo_usuario

        result = executar_cancelamento_pelo_usuario(user)
    except ValueError as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)
    except Exception as e:
        logger.exception("Erro ao cancelar assinatura: %s", e)
        return JsonResponse(
            {"success": False, "message": "Erro ao cancelar assinatura no Mercado Pago."},
            status=500,
        )

    return JsonResponse(result)


def agenda_api_view(request):
    """
    API endpoint para listar compromissos (formato FullCalendar).
    
    GET /finance/api/agenda/?start=2026-01-01&end=2026-01-31
    
    SEGURANÇA: user_id é extraído do request.user_mongo (garantido pelo middleware).
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    
    try:
        user_id = str(request.user_mongo['_id'])
        logger.info(f"[AGENDA_API] Buscando compromissos para user_id: {user_id}")
        
        # Obter parâmetros de data do FullCalendar
        start_str = request.GET.get('start')
        end_str = request.GET.get('end')
        
        logger.info(f"[AGENDA_API] Parâmetros recebidos - start: {start_str}, end: {end_str}")
        
        # Valores padrão
        start_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = (datetime.utcnow() + timedelta(days=30)).replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Função auxiliar para parse de datas com múltiplos formatos
        def parse_date(date_str):
            """Parse de data com suporte a múltiplos formatos."""
            if not date_str:
                return None
            
            # Remover espaços
            date_str = date_str.strip()
            
            # Normalizar fuso horário: converter +HH:MM para +HHMM (formato Python strptime)
            # Python strptime requer +HHMM ou -HHMM, não +HH:MM
            import re
            # Padrão: -03:00 ou +03:00 -> -0300 ou +0300
            date_str = re.sub(r'([+-])(\d{2}):(\d{2})$', r'\1\2\3', date_str)
            
            # Lista de formatos a tentar (ordem importa - mais específicos primeiro)
            formats = [
                '%Y-%m-%dT%H:%M:%S.%f%z',  # Com microsegundos e fuso: 2026-01-13T00:00:00.000-0300
                '%Y-%m-%dT%H:%M:%S%z',  # Com fuso horário: 2026-01-13T00:00:00-0300
                '%Y-%m-%dT%H:%M:%S',  # Sem fuso: 2026-01-13T00:00:00
                '%Y-%m-%dT%H:%M',  # Sem segundos: 2026-01-13T00:00
                '%Y-%m-%d',  # Apenas data: 2026-01-13
            ]
            
            for fmt in formats:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    # Se tem fuso horário, converter para UTC e remover timezone
                    if dt.tzinfo is not None:
                        # Converter para UTC e depois remover timezone info
                        from datetime import timezone
                        dt_utc = dt.astimezone(timezone.utc)  # Converte para UTC
                        dt = dt_utc.replace(tzinfo=None)  # Remove timezone info (naive UTC)
                    # Se não tem fuso horário, manter como está (assumir UTC)
                    logger.info(f"[AGENDA_API] Data parseada com sucesso: {date_str} -> {dt} (formato: {fmt})")
                    return dt
                except ValueError:
                    continue
                except Exception as e:
                    logger.warning(f"[AGENDA_API] Erro ao tentar formato {fmt}: {e}")
                    continue
            
            # Tentar com dateutil como fallback (mais flexível)
            try:
                from dateutil import parser
                from datetime import timezone
                dt = parser.parse(date_str)
                # Se tem timezone, converter para UTC e remover
                if dt.tzinfo is not None:
                    dt_utc = dt.astimezone(timezone.utc)
                    dt = dt_utc.replace(tzinfo=None)
                logger.info(f"[AGENDA_API] Data parseada com dateutil: {date_str} -> {dt}")
                return dt
            except Exception as e:
                logger.error(f"[AGENDA_API] Erro ao fazer parse da data {date_str}: {e}")
                raise ValueError(f"Formato de data inválido: {date_str}")
        
        # Parse das datas
        if start_str:
            try:
                start_date = parse_date(start_str)
                if start_date:
                    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            except Exception as e:
                logger.error(f"[AGENDA_API] Erro ao parsear start_date: {e}")
                return JsonResponse({
                    'error': 'Formato de data inicial inválido',
                    'message': str(e),
                    'received': start_str
                }, status=400)
        
        if end_str:
            try:
                end_date = parse_date(end_str)
                if end_date:
                    end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            except Exception as e:
                logger.error(f"[AGENDA_API] Erro ao parsear end_date: {e}")
                return JsonResponse({
                    'error': 'Formato de data final inválido',
                    'message': str(e),
                    'received': end_str
                }, status=400)
        
        logger.info(f"[AGENDA_API] Buscando compromissos de {start_date} até {end_date}")
        
        # Buscar compromissos
        try:
            service = CompromissoService()
            compromissos = service.listar_compromissos(user_id, start_date, end_date)
            logger.info(f"[AGENDA_API] {len(compromissos)} compromissos encontrados")
            
            # Formatar para FullCalendar
            eventos = service.formatar_para_calendario(compromissos)
            logger.info(f"[AGENDA_API] {len(eventos)} eventos formatados")
            
            return JsonResponse(eventos, safe=False, json_dumps_params={'ensure_ascii': False})
            
        except Exception as e:
            logger.error(f"[AGENDA_API] Erro ao buscar compromissos: {e}", exc_info=True)
            return JsonResponse({
                'error': 'Erro ao buscar compromissos no banco de dados',
                'message': str(e)
            }, status=500)
        
    except Exception as e:
        logger.error(f"[AGENDA_API] Erro geral: {e}", exc_info=True)
        return JsonResponse({
            'error': 'Erro ao processar requisição',
            'message': str(e)
        }, status=500)


def criar_compromisso_api_view(request):
    """
    API endpoint para criar compromisso.
    
    POST /finance/api/compromissos/create/
    
    Body JSON:
    {
        "titulo": "Reunião",
        "descricao": "Reunião com equipe",
        "data": "2026-01-15",
        "hora": "14:00",
        "tipo": "Reunião"
    }
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido'}, status=405)
    
    try:
        user_id = str(request.user_mongo['_id'])
        import json
        data = json.loads(request.body)
        
        titulo = data.get('titulo', '').strip()
        descricao = data.get('descricao', '').strip()
        data_compromisso = data.get('data', '').strip()
        hora = data.get('hora', '').strip()
        hora_fim = data.get('hora_fim', '').strip()
        tipo = data.get('tipo', '').strip()
        
        if not titulo:
            return JsonResponse({'error': 'Título é obrigatório'}, status=400)
        
        if not data_compromisso:
            return JsonResponse({'error': 'Data é obrigatória'}, status=400)
        
        if not hora:
            return JsonResponse({'error': 'Horário de início é obrigatório'}, status=400)
        
        if not hora_fim:
            return JsonResponse({'error': 'Horário de término é obrigatório'}, status=400)
        
        # Validar que hora_fim é posterior a hora
        try:
            hora_parts = hora.split(':')
            hora_fim_parts = hora_fim.split(':')
            hora_minutos = int(hora_parts[0]) * 60 + int(hora_parts[1])
            hora_fim_minutos = int(hora_fim_parts[0]) * 60 + int(hora_fim_parts[1])
            
            if hora_fim_minutos <= hora_minutos:
                return JsonResponse({'error': 'O horário de término deve ser posterior ao horário de início'}, status=400)
        except:
            return JsonResponse({'error': 'Formato de horário inválido'}, status=400)
        
        service = CompromissoService()
        compromisso = service.criar_compromisso(
            user_id=user_id,
            titulo=titulo,
            descricao=descricao,
            data=data_compromisso,
            hora=hora,
            hora_fim=hora_fim,
            tipo=tipo if tipo else None
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Compromisso criado com sucesso!',
            'compromisso': {
                'id': str(compromisso.get('_id')),
                'titulo': compromisso.get('titulo'),
                'descricao': compromisso.get('descricao'),
                'data': compromisso.get('data').isoformat() if isinstance(compromisso.get('data'), datetime) else compromisso.get('data'),
                'hora': compromisso.get('hora'),
                'hora_inicio': compromisso.get('hora_inicio') or compromisso.get('hora'),
                'hora_fim': compromisso.get('hora_fim'),
                'tipo': compromisso.get('tipo'),
                'status': compromisso.get('status')
            }
        }, json_dumps_params={'ensure_ascii': False})
        
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({
            'error': 'Erro ao criar compromisso',
            'message': str(e)
        }, status=500)


def atualizar_compromisso_api_view(request, compromisso_id):
    """
    API endpoint para atualizar compromisso.
    
    PUT /finance/api/compromissos/<id>/update/
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    
    if request.method not in ['PUT', 'PATCH']:
        return JsonResponse({'error': 'Método não permitido'}, status=405)
    
    try:
        user_id = str(request.user_mongo['_id'])
        import json
        data = json.loads(request.body)
        
        hora_fim = data.get('hora_fim', '').strip()
        
        # Validar hora_fim se fornecido
        if hora_fim and data.get('hora'):
            try:
                hora = data.get('hora', '').strip()
                hora_parts = hora.split(':')
                hora_fim_parts = hora_fim.split(':')
                hora_minutos = int(hora_parts[0]) * 60 + int(hora_parts[1])
                hora_fim_minutos = int(hora_fim_parts[0]) * 60 + int(hora_fim_parts[1])
                
                if hora_fim_minutos <= hora_minutos:
                    return JsonResponse({'error': 'O horário de término deve ser posterior ao horário de início'}, status=400)
            except:
                return JsonResponse({'error': 'Formato de horário inválido'}, status=400)
        
        service = CompromissoService()
        compromisso = service.atualizar_compromisso(
            compromisso_id=compromisso_id,
            user_id=user_id,
            titulo=data.get('titulo'),
            descricao=data.get('descricao'),
            data=data.get('data'),
            hora=data.get('hora'),
            hora_fim=hora_fim if hora_fim else None,
            tipo=data.get('tipo'),
            status=data.get('status')
        )
        
        if not compromisso:
            return JsonResponse({'error': 'Compromisso não encontrado'}, status=404)
        
        return JsonResponse({
            'success': True,
            'message': 'Compromisso atualizado com sucesso!',
            'compromisso': {
                'id': str(compromisso.get('_id')),
                'titulo': compromisso.get('titulo'),
                'descricao': compromisso.get('descricao'),
                'data': compromisso.get('data').isoformat() if isinstance(compromisso.get('data'), datetime) else compromisso.get('data'),
                'hora': compromisso.get('hora'),
                'hora_inicio': compromisso.get('hora_inicio') or compromisso.get('hora'),
                'hora_fim': compromisso.get('hora_fim'),
                'tipo': compromisso.get('tipo'),
                'status': compromisso.get('status')
            }
        }, json_dumps_params={'ensure_ascii': False})
        
    except PermissionError as e:
        return JsonResponse({'error': str(e)}, status=403)
    except Exception as e:
        return JsonResponse({
            'error': 'Erro ao atualizar compromisso',
            'message': str(e)
        }, status=500)


def excluir_compromisso_api_view(request, compromisso_id):
    """
    API endpoint para excluir compromisso.
    
    DELETE /finance/api/compromissos/<id>/delete/
    """
    if not hasattr(request, 'user_mongo') or not request.user_mongo:
        return JsonResponse({'error': 'Não autenticado'}, status=401)
    
    if request.method != 'DELETE':
        return JsonResponse({'error': 'Método não permitido'}, status=405)
    
    try:
        user_id = str(request.user_mongo['_id'])
        
        service = CompromissoService()
        sucesso = service.excluir_compromisso(compromisso_id, user_id)
        
        if not sucesso:
            return JsonResponse({'error': 'Compromisso não encontrado'}, status=404)
        
        return JsonResponse({
            'success': True,
            'message': 'Compromisso excluído com sucesso!'
        }, json_dumps_params={'ensure_ascii': False})
        
    except PermissionError as e:
        return JsonResponse({'error': str(e)}, status=403)
    except Exception as e:
        return JsonResponse({
            'error': 'Erro ao excluir compromisso',
            'message': str(e)
        }, status=500)
