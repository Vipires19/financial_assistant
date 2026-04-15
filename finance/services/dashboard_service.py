"""
Service para gerar dados do dashboard financeiro.

Localização: finance/services/dashboard_service.py

Este service gera todas as métricas e dados necessários para o dashboard,
usando agregações do MongoDB para máxima performance.
"""
import calendar
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta, timezone
from finance.repositories.transaction_repository import TransactionRepository
from core.repositories.user_repository import UserRepository
from core.services.user_scope import resolve_user_read_scope
from core.services.family_ui_service import (
    build_family_context,
    member_id_to_display_names,
)


# Estágio de agregação: data efetiva da transação (transaction_date ou created_at para compatibilidade)
_EFFECTIVE_DATE_STAGE = {'$addFields': {'_effective_date': {'$ifNull': ['$transaction_date', '$created_at']}}}


class DashboardService:
    """
    Service para gerar dados do dashboard financeiro.
    
    Exemplo de uso:
        service = DashboardService()
        data = service.get_dashboard_data(
            user=request.user_mongo,
            period='mensal'
        )
    """
    
    def __init__(self):
        self.transaction_repo = TransactionRepository()
        self.user_repo = UserRepository()
    
    def get_dashboard_data(self, user: Dict[str, Any], period: str = 'mensal', month: Optional[int] = None, year: Optional[int] = None) -> Dict[str, Any]:
        """
        Gera todos os dados do dashboard financeiro.
        
        Leitura: escopo família quando aplicável (ver ``core.services.user_scope``).
        
        Args:
            user: Documento do usuário MongoDB (obrigatório; ex.: request.user_mongo)
            period: Período de filtro ('diário', 'semanal', 'mensal')
        
        Returns:
            Dict com todos os dados do dashboard:
            - total_expenses: Total de gastos
            - total_income: Total de entradas
            - balance: Saldo (entradas - gastos)
            - day_with_highest_expense: Dia com maior gasto
            - category_with_highest_expense: Categoria com maior gasto
            - hour_with_highest_expense: Horário com maior gasto
            - transactions: Lista de transações filtradas
        
        Raises:
            ValueError: Se usuário inválido
        """
        if not user or not user.get('_id'):
            raise ValueError("user é obrigatório para acessar dados do dashboard")

        scope, _member_ids = resolve_user_read_scope(user)

        # Calcula datas do período
        start_date, end_date = self._get_period_dates(period, month, year)
        
        # Executa todas as agregações em paralelo (via pipeline único otimizado)
        data = {
            'period': period,
            'start_date': start_date,
            'end_date': end_date,
            'family_context': build_family_context(user),
        }
        
        # Totais (gastos, entradas, saldo)
        totals = self._get_totals(scope, start_date, end_date)
        data.update(totals)
        
        # Dia com maior gasto
        data['day_with_highest_expense'] = self._get_day_with_highest_expense(
            scope, start_date, end_date
        )
        
        # Categoria com maior gasto
        data['category_with_highest_expense'] = self._get_category_with_highest_expense(
            scope, start_date, end_date
        )
        
        # Horário com maior gasto
        data['hour_with_highest_expense'] = self._get_hour_with_highest_expense(
            scope, start_date, end_date
        )
        
        # Lista de transações filtradas (sem paginação no método principal)
        transactions_data = self._get_filtered_transactions(
            scope, start_date, end_date, limit=50, skip=0, viewer=user
        )
        data['transactions'] = transactions_data['transactions']
        data['transactions_pagination'] = transactions_data['pagination']

        # Saldo por conta e saldo total (user.contas + transações; credit_card não entra no total)
        balances = self._get_balances_by_account(user)
        data['total_balance'] = balances['total_balance']
        data['accounts'] = balances['accounts']
        data['credit_cards'] = balances.get('credit_cards', [])
        
        # Top 3 categorias com maior gasto no período
        data['top_expense_categories'] = self.get_top_expense_categories(
            user, period, month, year
        )
        
        return data
    
    def _get_period_dates(self, period: str, month: Optional[int] = None, year: Optional[int] = None) -> Tuple[datetime, datetime]:
        """
        Calcula as datas de início e fim do período.
        Respeita month e year quando informados (filtros do dashboard).
        Todas as datas em UTC para compatibilidade com transaction_date/created_at no MongoDB.

        Args:
            period: 'diário'/'diario', 'semanal', 'mensal', 'anual' ou 'geral'
            month: Mês (1-12) para período mensal (opcional, da query string).
            year: Ano para período mensal ou anual (opcional, da query string).

        Returns:
            Tupla (start_date, end_date)
        """
        now = datetime.now(timezone.utc)
        period = (period or '').strip().lower()

        if period in ('diário', 'diario'):
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now

        elif period == 'semanal':
            start = now - timedelta(days=7)
            end = now

        elif period == 'mensal':
            if month and year:
                try:
                    month = int(month)
                    year = int(year)
                except (ValueError, TypeError):
                    month = None
                    year = None
            if month and year:
                start = datetime(year, month, 1, tzinfo=timezone.utc)
                last_day = calendar.monthrange(year, month)[1]
                end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
            else:
                start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                end = now

        elif period == 'anual':
            if year:
                try:
                    year = int(year)
                except (ValueError, TypeError):
                    year = None
            if year:
                start = datetime(year, 1, 1, tzinfo=timezone.utc)
                end = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
            else:
                start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
                end = now

        elif period == 'geral':
            # Janela longa para padrões de comportamento (insights “geral”, não um mês isolado)
            start = now - timedelta(days=730)
            end = now

        else:
            start = now - timedelta(days=30)
            end = now

        return start, end
    
    def _get_totals(self, scope: Dict[str, Any], start_date: datetime,
                    end_date: datetime) -> Dict[str, float]:
        """
        Calcula totais de gastos, entradas e saldo usando agregação.
        
        Args:
            scope: Filtro de escopo de leitura (user_id ou user_id $in)
            start_date: Data inicial
            end_date: Data final
        
        Returns:
            Dict com total_expenses, total_income, balance
        """
        pipeline = [
            _EFFECTIVE_DATE_STAGE,
            {
                '$match': {
                    **scope,
                    '_effective_date': {
                        '$gte': start_date,
                        '$lte': end_date
                    }
                }
            },
            {
                '$group': {
                    '_id': '$type',
                    'total': {'$sum': '$value'}
                }
            }
        ]
        
        results = list(self.transaction_repo.collection.aggregate(pipeline))
        
        total_income = sum(r['total'] for r in results if r['_id'] == 'income')
        total_expense = sum(r['total'] for r in results if r['_id'] == 'expense')
        
        return {
            'total_expenses': total_expense,
            'total_income': total_income,
            'balance': total_income - total_expense
        }

    def _get_balances_by_account(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calcula saldo de cada conta (user.contas) com base em saldo_inicial e transações.
        Para todas: saldo = saldo_inicial + income - expense.
        total_balance = soma apenas de contas que NÃO são credit_card.
        Contas do tipo credit_card vão em credit_cards e não entram no total_balance.

        Escopo de leitura: família quando aplicável (contas e transações de todos os membros).

        Returns:
            Dict com total_balance (float), accounts (lista de {id, nome, balance}),
            credit_cards (lista de {id, nome, balance}).
        """
        scope, member_ids = resolve_user_read_scope(user)

        # Busca todas as transações do escopo (sem filtro de período, para saldo acumulado)
        transactions = self.transaction_repo.find_many(
            query=dict(scope),
            limit=50000,
            skip=0,
            sort=('created_at', 1)
        )

        total_balance = 0.0
        accounts = []
        credit_cards = []

        for mid in member_ids:
            u = self.user_repo.find_by_id(str(mid))
            contas = (u or {}).get('contas') or []

            for conta in contas:
                conta_id = conta.get('id')
                nome = conta.get('nome') or '-'
                tipo = conta.get('tipo') or ''
                saldo_inicial = float(conta.get('saldo_inicial') or 0)
                balance = saldo_inicial

                for trans in transactions:
                    if str(trans.get('user_id')) != str(mid):
                        continue
                    if trans.get('account_id') != conta_id:
                        continue
                    value = float(trans.get('value') or 0)
                    if trans.get('type') == 'income':
                        balance += value
                    else:
                        balance -= value

                item = {
                    'id': conta_id,
                    'nome': nome,
                    'balance': round(balance, 2),
                }
                if tipo == 'credit_card':
                    credit_cards.append(item)
                else:
                    total_balance += balance
                    accounts.append(item)

        return {
            'total_balance': round(total_balance, 2),
            'accounts': accounts,
            'credit_cards': credit_cards,
        }

    def get_account_balances(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """
        Retorna saldo total e saldo por conta para o escopo de leitura (família ou individual).
        Útil para expor via API GET /finance/api/accounts/balance/
        """
        return self._get_balances_by_account(user)

    def _get_day_with_highest_expense(self, scope: Dict[str, Any], start_date: datetime,
                                     end_date: datetime) -> Optional[Dict[str, Any]]:
        """
        Encontra o dia com maior gasto usando agregação.
        
        Args:
            scope: Filtro de escopo de leitura
            start_date: Data inicial
            end_date: Data final
        
        Returns:
            Dict com date e total, ou None se não houver gastos
        """
        pipeline = [
            _EFFECTIVE_DATE_STAGE,
            {
                '$match': {
                    **scope,
                    'type': 'expense',
                    '_effective_date': {
                        '$gte': start_date,
                        '$lte': end_date
                    }
                }
            },
            {
                '$group': {
                    '_id': {
                        '$dateToString': {
                            'format': '%Y-%m-%d',
                            'date': '$_effective_date'
                        }
                    },
                    'total': {'$sum': '$value'},
                    'date': {'$first': '$_effective_date'}
                }
            },
            {'$sort': {'total': -1}},
            {'$limit': 1}
        ]
        
        results = list(self.transaction_repo.collection.aggregate(pipeline))
        
        if results:
            date_obj = results[0]['_id']
            if isinstance(date_obj, datetime):
                formatted_date = date_obj.strftime('%d/%m/%Y')
            elif isinstance(date_obj, str):
                # Se for string no formato YYYY-MM-DD, converte
                try:
                    from dateutil import parser
                    dt = parser.parse(date_obj)
                    formatted_date = dt.strftime('%d/%m/%Y')
                except:
                    formatted_date = date_obj
            else:
                formatted_date = str(date_obj)
            
            return {
                'date': results[0]['_id'],
                'total': results[0]['total'],
                'formatted_date': formatted_date
            }
        
        return None
    
    def _get_category_with_highest_expense(self, scope: Dict[str, Any], start_date: datetime,
                                         end_date: datetime) -> Optional[Dict[str, Any]]:
        """
        Encontra a categoria com maior gasto usando agregação.
        
        Args:
            scope: Filtro de escopo de leitura
            start_date: Data inicial
            end_date: Data final
        
        Returns:
            Dict com category e total, ou None se não houver gastos
        """
        pipeline = [
            _EFFECTIVE_DATE_STAGE,
            {
                '$match': {
                    **scope,
                    'type': 'expense',
                    '_effective_date': {
                        '$gte': start_date,
                        '$lte': end_date
                    }
                }
            },
            {
                '$group': {
                    '_id': '$category',
                    'total': {'$sum': '$value'},
                    'count': {'$sum': 1}
                }
            },
            {'$sort': {'total': -1}},
            {'$limit': 1}
        ]
        
        results = list(self.transaction_repo.collection.aggregate(pipeline))
        
        if results:
            return {
                'category': results[0]['_id'],
                'total': results[0]['total'],
                'count': results[0]['count']
            }
        
        return None
    
    def get_top_expense_categories(self, user: Dict[str, Any], period: str = 'mensal',
                                    month: Optional[int] = None, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retorna as 3 categorias com maior gasto no período (ranking).
        
        Args:
            user: Documento do usuário (escopo de leitura: família quando aplicável)
            period: 'diário', 'semanal', 'mensal' ou 'anual'
            month: Mês (1-12) opcional
            year: Ano opcional
        
        Returns:
            Lista de até 3 itens: [{"category": str, "total": float}, ...]
        """
        if not user or not user.get('_id'):
            return []
        scope, _ = resolve_user_read_scope(user)
        start_date, end_date = self._get_period_dates(period, month, year)
        pipeline = [
            _EFFECTIVE_DATE_STAGE,
            {
                '$match': {
                    **scope,
                    'type': 'expense',
                    '_effective_date': {'$gte': start_date, '$lte': end_date}
                }
            },
            {
                '$group': {
                    '_id': '$category',
                    'total': {'$sum': '$value'}
                }
            },
            {'$sort': {'total': -1}},
            {'$limit': 3}
        ]
        results = list(self.transaction_repo.collection.aggregate(pipeline))
        return [
            {'category': (r['_id'] or 'outros'), 'total': float(r['total'])}
            for r in results
        ]
    
    def _get_hour_with_highest_expense(self, scope: Dict[str, Any], start_date: datetime,
                                      end_date: datetime) -> Optional[Dict[str, Any]]:
        """
        Encontra o horário com maior gasto usando agregação.
        
        Usa o campo 'hour' extraído para máxima performance.
        
        Args:
            scope: Filtro de escopo de leitura
            start_date: Data inicial
            end_date: Data final
        
        Returns:
            Dict com hour e total, ou None se não houver gastos
        """
        pipeline = [
            _EFFECTIVE_DATE_STAGE,
            {
                '$match': {
                    **scope,
                    'type': 'expense',
                    '_effective_date': {
                        '$gte': start_date,
                        '$lte': end_date
                    }
                }
            },
            {
                '$group': {
                    '_id': {'$hour': '$_effective_date'},
                    'total': {'$sum': '$value'},
                    'count': {'$sum': 1}
                }
            },
            {
                '$sort': {'total': -1}
            },
            {
                '$limit': 1
            }
        ]
        
        # Acessa collection diretamente para agregações complexas
        # (isso é aceitável para agregações que não são CRUD simples)
        results = list(self.transaction_repo.collection.aggregate(pipeline))
        
        if results:
            hour = results[0]['_id']
            return {
                'hour': hour,
                'total': results[0]['total'],
                'count': results[0]['count'],
                'formatted_hour': f"{hour:02d}:00"
            }
        
        return None
    
    def _get_filtered_transactions(self, scope: Dict[str, Any], start_date: datetime,
                                  end_date: datetime, limit: int = 50,
                                  skip: int = 0,
                                  viewer: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Retorna lista de transações filtradas por período com paginação.
        
        Args:
            scope: Filtro de escopo de leitura (user_id ou user_id $in)
            start_date: Data inicial
            end_date: Data final
            limit: Limite de resultados por página
            skip: Quantidade a pular (para paginação)
        
        Returns:
            Dict com:
            - transactions: Lista de transações
            - total: Total de transações
            - page: Página atual
            - limit: Limite por página
            - has_next: Se há próxima página
            - has_prev: Se há página anterior
        
        Raises:
            ValueError: Se escopo vazio
        """
        if not scope:
            raise ValueError("escopo de leitura é obrigatório")

        owner_labels: Dict[str, str] = {}
        viewer_id_str = ""
        if viewer and viewer.get("_id"):
            viewer_id_str = str(viewer["_id"])
            _, mids = resolve_user_read_scope(viewer)
            owner_labels = member_id_to_display_names(mids)
        
        # Usa agregação para filtrar por data efetiva (transaction_date ou created_at)
        pipeline_count = [
            _EFFECTIVE_DATE_STAGE,
            {'$match': {**scope, '_effective_date': {'$gte': start_date, '$lte': end_date}}},
            {'$count': 'total'}
        ]
        count_result = list(self.transaction_repo.collection.aggregate(pipeline_count))
        total = count_result[0]['total'] if count_result else 0
        
        pipeline_list = [
            _EFFECTIVE_DATE_STAGE,
            {'$match': {**scope, '_effective_date': {'$gte': start_date, '$lte': end_date}}},
            {'$sort': {'_effective_date': -1}},
            {'$skip': skip},
            {'$limit': limit}
        ]
        transactions = list(self.transaction_repo.collection.aggregate(pipeline_list))
        
        current_page = (skip // limit) + 1
        total_pages = (total + limit - 1) // limit if total > 0 else 1
        has_next = skip + limit < total
        has_prev = skip > 0
        
        formatted = []
        for trans in transactions:
            data_transacao = trans.get('transaction_date') or trans.get('created_at')
            if isinstance(data_transacao, datetime):
                date_str = data_transacao.strftime('%d/%m/%Y')
                time_str = data_transacao.strftime('%H:%M')
            else:
                try:
                    from dateutil import parser
                    dt = parser.parse(data_transacao) if isinstance(data_transacao, str) else data_transacao
                    date_str = dt.strftime('%d/%m/%Y')
                    time_str = dt.strftime('%H:%M')
                except (TypeError, ValueError):
                    date_str = str(data_transacao) if data_transacao else ''
                    time_str = ''
            
            tuid = trans.get('user_id')
            owner_key = str(tuid) if tuid is not None else ''
            owner_name = owner_labels.get(owner_key, 'Membro') if owner_labels else '—'
            is_mine = bool(viewer_id_str and owner_key == viewer_id_str)

            formatted.append({
                'id': str(trans['_id']),
                'type': trans['type'],
                'category': trans.get('category', 'outros'),
                'description': trans['description'],
                'value': float(trans['value']),
                'date': date_str,
                'time': time_str,
                'created_at': data_transacao.isoformat() if isinstance(data_transacao, datetime) else str(data_transacao) if data_transacao else '',
                'hour': trans.get('hour', None),
                'account_id': str(trans['account_id']) if trans.get('account_id') else None,
                'owner_user_id': owner_key,
                'owner_name': owner_name,
                'is_mine': is_mine,
            })
        
        return {
            'transactions': formatted,
            'pagination': {
                'total': total,
                'page': current_page,
                'limit': limit,
                'total_pages': total_pages,
                'has_next': has_next,
                'has_prev': has_prev
            }
        }
    
    # ==================== MÉTODOS PARA GRÁFICOS (Chart.js) ====================
    
    def get_expenses_by_category_chart_data(self, user: Dict[str, Any],
                                           period: str = 'mensal', month: Optional[int] = None, year: Optional[int] = None) -> Dict[str, Any]:
        """
        Gera dados para gráfico de despesas e entradas por categoria (Chart.js).
        
        Mostra tanto entradas quanto gastos agrupados por categoria.
        
        Args:
            user: Documento do usuário MongoDB
            period: Período ('diário', 'semanal', 'mensal', 'anual')
            month: Mês (1-12) quando period mensal (opcional).
            year: Ano quando period mensal ou anual (opcional).
        
        Returns:
            Dict no formato Chart.js com dois datasets (entradas e gastos)
        """
        scope, _ = resolve_user_read_scope(user)
        start_date, end_date = self._get_period_dates(period, month, year)
        
        # Pipeline para gastos
        pipeline_expenses = [
            _EFFECTIVE_DATE_STAGE,
            {
                '$match': {
                    **scope,
                    'type': 'expense',
                    '_effective_date': {
                        '$gte': start_date,
                        '$lte': end_date
                    }
                }
            },
            {
                '$group': {
                    '_id': '$category',
                    'total': {'$sum': '$value'}
                }
            },
            {
                '$sort': {'total': -1}
            }
        ]
        
        # Pipeline para entradas
        pipeline_incomes = [
            _EFFECTIVE_DATE_STAGE,
            {
                '$match': {
                    **scope,
                    'type': 'income',
                    '_effective_date': {
                        '$gte': start_date,
                        '$lte': end_date
                    }
                }
            },
            {
                '$group': {
                    '_id': '$category',
                    'total': {'$sum': '$value'}
                }
            },
            {
                '$sort': {'total': -1}
            }
        ]
        
        results_expenses = list(self.transaction_repo.collection.aggregate(pipeline_expenses))
        results_incomes = list(self.transaction_repo.collection.aggregate(pipeline_incomes))
        
        # Combina todas as categorias (de gastos e entradas)
        all_categories = set()
        for r in results_expenses:
            all_categories.add(r['_id'])
        for r in results_incomes:
            all_categories.add(r['_id'])
        
        labels = sorted(list(all_categories))
        
        # Cria dicionários para acesso rápido
        expenses_dict = {r['_id']: float(r['total']) for r in results_expenses}
        incomes_dict = {r['_id']: float(r['total']) for r in results_incomes}
        
        # Prepara dados
        expenses_data = [expenses_dict.get(cat, 0.0) for cat in labels]
        incomes_data = [incomes_dict.get(cat, 0.0) for cat in labels]
        
        # Paleta de cores determinística
        color_palette = [
            'rgba(239, 68, 68, 0.6)',   # Vermelho (gastos)
            'rgba(34, 197, 94, 0.6)',   # Verde (entradas)
            'rgba(59, 130, 246, 0.6)',  # Azul
            'rgba(168, 85, 247, 0.6)',  # Roxo
            'rgba(251, 146, 60, 0.6)',  # Laranja
            'rgba(236, 72, 153, 0.6)',  # Rosa
            'rgba(14, 165, 233, 0.6)',  # Ciano
            'rgba(132, 204, 22, 0.6)',  # Lima
            'rgba(245, 158, 11, 0.6)',  # Amarelo
            'rgba(139, 92, 246, 0.6)',  # Violeta
        ]
        
        background_colors = []
        border_colors = []
        
        for label in labels:
            color_index = hash(label) % len(color_palette)
            color = color_palette[abs(color_index)]
            background_colors.append(color.replace('0.6', '0.2'))
            border_colors.append(color.replace('0.6', '1'))
        
        if len(labels) == 0:
            labels = ['Nenhum dado']
            expenses_data = [0]
            incomes_data = [0]
            background_colors = ['rgba(200, 200, 200, 0.2)']
            border_colors = ['rgba(200, 200, 200, 1)']
        
        return {
            'labels': labels,
            'datasets': [
                {
                    'label': 'Gastos',
                    'data': expenses_data,
                    'backgroundColor': 'rgba(239, 68, 68, 0.2)',
                    'borderColor': 'rgba(239, 68, 68, 1)',
                    'borderWidth': 2
                },
                {
                    'label': 'Entradas',
                    'data': incomes_data,
                    'backgroundColor': 'rgba(34, 197, 94, 0.2)',
                    'borderColor': 'rgba(34, 197, 94, 1)',
                    'borderWidth': 2
                }
            ]
        }
    
    def get_expenses_by_weekday_chart_data(self, user: Dict[str, Any],
                                          period: str = 'mensal', month: Optional[int] = None, year: Optional[int] = None) -> Dict[str, Any]:
        """
        Gera dados para gráfico de despesas por dia da semana (Chart.js).
        
        Args:
            user: Documento do usuário MongoDB
            period: Período ('diário', 'semanal', 'mensal')
        
        Returns:
            Dict no formato Chart.js
        """
        if not user or not user.get('_id'):
            raise ValueError("user é obrigatório")
        scope, _ = resolve_user_read_scope(user)
        start_date, end_date = self._get_period_dates(period, month, year)
        
        # Nomes dos dias da semana em português
        weekday_names = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb']
        
        # Busca transações de despesas no período (data efetiva = transaction_date ou created_at)
        pipeline = [
            _EFFECTIVE_DATE_STAGE,
            {
                '$match': {
                    **scope,
                    'type': 'expense',
                    '_effective_date': {'$gte': start_date, '$lte': end_date}
                }
            },
            {'$limit': 10000}
        ]
        transactions = list(self.transaction_repo.collection.aggregate(pipeline))
        
        weekday_names = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
        data_by_weekday = [0.0] * 7
        
        for trans in transactions:
            data_transacao = trans.get('transaction_date') or trans.get('created_at')
            if isinstance(data_transacao, datetime):
                weekday_index = data_transacao.weekday()
                if 0 <= weekday_index < 7:
                    data_by_weekday[weekday_index] += float(trans.get('value', 0))
        
        return {
            'labels': weekday_names,
            'datasets': [{
                'label': 'Gastos por Dia da Semana',
                'data': data_by_weekday,
                'backgroundColor': 'rgba(239, 68, 68, 0.5)',
                'borderColor': 'rgba(239, 68, 68, 1)',
                'borderWidth': 2
            }]
        }
    
    def get_expenses_by_hour_chart_data(self, user: Dict[str, Any],
                                       period: str = 'mensal', month: Optional[int] = None, year: Optional[int] = None) -> Dict[str, Any]:
        """
        Gera dados para gráfico de despesas por horário do dia (Chart.js).
        
        Usa o campo 'hour' extraído para máxima performance.
        
        Args:
            user: Documento do usuário MongoDB
            period: Período ('diário', 'semanal', 'mensal', 'anual')
            month: Mês (1-12) quando period mensal (opcional).
            year: Ano quando period mensal ou anual (opcional).
        
        Returns:
            Dict no formato Chart.js
        """
        if not user or not user.get('_id'):
            raise ValueError("user é obrigatório")
        scope, _ = resolve_user_read_scope(user)
        start_date, end_date = self._get_period_dates(period, month, year)
        
        pipeline = [
            _EFFECTIVE_DATE_STAGE,
            {
                '$match': {
                    **scope,
                    'type': 'expense',
                    '_effective_date': {
                        '$gte': start_date,
                        '$lte': end_date
                    }
                }
            },
            {
                '$group': {
                    '_id': {'$hour': '$_effective_date'},
                    'total': {'$sum': '$value'}
                }
            },
            {'$sort': {'_id': 1}}
        ]
        
        results = list(self.transaction_repo.collection.aggregate(pipeline))
        
        labels = [f"{h:02d}:00" for h in range(24)]
        data_by_hour = [0.0] * 24
        
        for result in results:
            hour = result['_id']
            if 0 <= hour < 24:
                data_by_hour[hour] = float(result['total'])
        
        return {
            'labels': labels,
            'datasets': [{
                'label': 'Gastos por Horário',
                'data': data_by_hour,
                'backgroundColor': 'rgba(239, 68, 68, 0.2)',
                'borderColor': 'rgba(239, 68, 68, 1)',
                'borderWidth': 2,
                'fill': True,
                'tension': 0.4
            }]
        }
    
    def get_chart_data_by_date(self, user: Dict[str, Any], period: str = 'mensal', month: Optional[int] = None, year: Optional[int] = None) -> Dict[str, Any]:
        """
        Gera dados para gráfico de saldo acumulado por data (Chart.js).
        
        Agrupa transações por data (YYYY-MM-DD), calcula saldo do dia (income - expense)
        e saldo acumulado ao longo dos dias. Usa a mesma lógica de período dos demais charts.
        
        Args:
            user: Documento do usuário MongoDB
            period: Período ('diário', 'semanal', 'mensal', 'anual')
            month: Mês (1-12) quando period mensal (opcional).
            year: Ano quando period mensal ou anual (opcional).
        
        Returns:
            Dict no formato Chart.js com labels (DD/MM) e dataset "Saldo Acumulado"
        """
        scope, _ = resolve_user_read_scope(user)
        start_date, end_date = self._get_period_dates(period, month, year)
        
        pipeline = [
            _EFFECTIVE_DATE_STAGE,
            {
                '$match': {
                    **scope,
                    '_effective_date': {'$gte': start_date, '$lte': end_date}
                }
            },
            {
                '$group': {
                    '_id': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$_effective_date'}},
                    'income': {'$sum': {'$cond': [{'$eq': ['$type', 'income']}, '$value', 0]}},
                    'expense': {'$sum': {'$cond': [{'$eq': ['$type', 'expense']}, '$value', 0]}}
                }
            },
            {'$sort': {'_id': 1}}
        ]
        
        results = list(self.transaction_repo.collection.aggregate(pipeline))
        
        labels = []
        saldo_acumulado_list = []
        saldo_acumulado = 0.0
        
        for r in results:
            date_str = r['_id']
            income = float(r.get('income', 0))
            expense = float(r.get('expense', 0))
            saldo_dia = income - expense
            saldo_acumulado += saldo_dia
            
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                labels.append(dt.strftime('%d/%m'))
            except (ValueError, TypeError):
                labels.append(date_str)
            saldo_acumulado_list.append(saldo_acumulado)
        
        return {
            'labels': labels,
            'datasets': [{
                'label': 'Saldo Acumulado',
                'data': saldo_acumulado_list,
                'borderColor': 'rgba(59,130,246,1)',
                'backgroundColor': 'rgba(59,130,246,0.2)',
                'fill': True,
                'tension': 0.4
            }]
        }

    def get_cash_flow_chart(self, user: Dict[str, Any], period: str = 'mensal',
                            month: Optional[int] = None, year: Optional[int] = None) -> Dict[str, Any]:
        """
        Gera dados para gráfico de fluxo de caixa (receitas, despesas e saldo por dia).
        Formato Chart.js com 3 datasets: Receitas, Despesas, Saldo (acumulado).
        """
        if not user or not user.get('_id'):
            return {'labels': [], 'datasets': []}
        scope, _ = resolve_user_read_scope(user)
        start_date, end_date = self._get_period_dates(period, month, year)
        pipeline = [
            _EFFECTIVE_DATE_STAGE,
            {
                '$match': {
                    **scope,
                    '_effective_date': {'$gte': start_date, '$lte': end_date}
                }
            },
            {
                '$group': {
                    '_id': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$_effective_date'}},
                    'income_total': {'$sum': {'$cond': [{'$eq': ['$type', 'income']}, '$value', 0]}},
                    'expense_total': {'$sum': {'$cond': [{'$eq': ['$type', 'expense']}, '$value', 0]}}
                }
            },
            {'$sort': {'_id': 1}}
        ]
        results = list(self.transaction_repo.collection.aggregate(pipeline))
        labels = []
        income_data = []
        expense_data = []
        balance_data = []
        saldo_acumulado = 0.0
        for r in results:
            date_str = r['_id']
            income = float(r.get('income_total', 0))
            expense = float(r.get('expense_total', 0))
            saldo_acumulado += income - expense
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                labels.append(dt.strftime('%d/%m'))
            except (ValueError, TypeError):
                labels.append(date_str)
            income_data.append(income)
            expense_data.append(expense)
            balance_data.append(saldo_acumulado)
        return {
            'labels': labels,
            'datasets': [
                {
                    'label': 'Receitas',
                    'data': income_data,
                    'borderColor': 'rgba(34,197,94,1)',
                    'backgroundColor': 'rgba(34,197,94,0.1)',
                    'fill': False,
                    'tension': 0.4
                },
                {
                    'label': 'Despesas',
                    'data': expense_data,
                    'borderColor': 'rgba(239,68,68,1)',
                    'backgroundColor': 'rgba(239,68,68,0.1)',
                    'fill': False,
                    'tension': 0.4
                },
                {
                    'label': 'Saldo',
                    'data': balance_data,
                    'borderColor': 'rgba(59,130,246,1)',
                    'backgroundColor': 'rgba(59,130,246,0.1)',
                    'fill': False,
                    'tension': 0.4
                }
            ]
        }

    def get_expenses_distribution(self, user: Dict[str, Any], period: str = 'mensal', month: Optional[int] = None, year: Optional[int] = None) -> Dict[str, Any]:
        """
        Gera dados para gráfico de distribuição de despesas por categoria (Chart.js).
        
        Agrupa despesas por categoria no período, ordenadas por total decrescente.
        Usa a mesma lógica de período (_get_period_dates).
        
        Args:
            user: Documento do usuário MongoDB
            period: Período ('diário', 'semanal', 'mensal', 'anual')
            month: Mês (1-12) quando period mensal (opcional).
            year: Ano quando period mensal ou anual (opcional).
        
        Returns:
            Dict no formato Chart.js: labels (categorias), datasets com data e backgroundColor
        """
        scope, _ = resolve_user_read_scope(user)
        start_date, end_date = self._get_period_dates(period, month, year)
        
        pipeline = [
            _EFFECTIVE_DATE_STAGE,
            {
                '$match': {
                    **scope,
                    'type': 'expense',
                    '_effective_date': {'$gte': start_date, '$lte': end_date}
                }
            },
            {
                '$group': {
                    '_id': '$category',
                    'total': {'$sum': '$value'}
                }
            },
            {'$sort': {'total': -1}}
        ]
        
        results = list(self.transaction_repo.collection.aggregate(pipeline))
        
        background_palette = [
            'rgba(239,68,68,0.8)',
            'rgba(59,130,246,0.8)',
            'rgba(16,185,129,0.8)',
            'rgba(234,179,8,0.8)',
            'rgba(168,85,247,0.8)',
            'rgba(244,114,182,0.8)'
        ]
        
        if not results:
            return {
                'labels': ['Sem dados'],
                'datasets': [{
                    'data': [0],
                    'backgroundColor': [background_palette[0]],
                    'borderWidth': 1
                }]
            }
        
        labels = [r['_id'] for r in results]
        data = [float(r['total']) for r in results]
        background_colors = [background_palette[i % len(background_palette)] for i in range(len(labels))]
        
        return {
            'labels': labels,
            'datasets': [{
                'data': data,
                'backgroundColor': background_colors,
                'borderWidth': 1
            }]
        }
    
    def get_expenses_by_account(self, user: Dict[str, Any], period: str = 'mensal', month: Optional[int] = None, year: Optional[int] = None) -> Dict[str, Any]:
        """
        Gera dados para gráfico de despesas por conta (Chart.js).
        
        Agrupa despesas por account_id no período, mapeia account_id para nome da conta
        (user.contas). Se a conta não existir mais, usa "Conta Removida".
        
        Args:
            user: Documento do usuário MongoDB
            period: Período ('diário', 'semanal', 'mensal', 'anual')
            month: Mês (1-12) quando period mensal (opcional).
            year: Ano quando period mensal ou anual (opcional).
        
        Returns:
            Dict no formato Chart.js: labels (nomes das contas), dataset "Despesas por Conta"
        """
        scope, member_ids = resolve_user_read_scope(user)
        start_date, end_date = self._get_period_dates(period, month, year)
        
        pipeline = [
            _EFFECTIVE_DATE_STAGE,
            {
                '$match': {
                    **scope,
                    'type': 'expense',
                    '_effective_date': {'$gte': start_date, '$lte': end_date}
                }
            },
            {
                '$group': {
                    '_id': '$account_id',
                    'total': {'$sum': '$value'}
                }
            },
            {'$sort': {'total': -1}}
        ]
        
        results = list(self.transaction_repo.collection.aggregate(pipeline))
        
        if not results:
            return {
                'labels': ['Sem dados'],
                'datasets': [{
                    'label': 'Despesas por Conta',
                    'data': [0],
                    'backgroundColor': 'rgba(239,68,68,0.6)',
                    'borderColor': 'rgba(239,68,68,1)',
                    'borderWidth': 2
                }]
            }
        
        id_to_nome: Dict[str, str] = {}
        for mid in member_ids:
            u = self.user_repo.find_by_id(str(mid))
            if not u:
                continue
            for conta in (u.get('contas') or []):
                cid = conta.get('id')
                if cid:
                    id_to_nome[str(cid)] = (conta.get('nome') or '') or ''
        
        labels = []
        data = []
        for r in results:
            account_id = r['_id']
            if account_id is None:
                account_id = ''
            label = id_to_nome.get(str(account_id), 'Conta Removida')
            labels.append(label)
            data.append(float(r['total']))
        
        return {
            'labels': labels,
            'datasets': [{
                'label': 'Despesas por Conta',
                'data': data,
                'backgroundColor': 'rgba(239,68,68,0.6)',
                'borderColor': 'rgba(239,68,68,1)',
                'borderWidth': 2
            }]
        }
    
    def get_income_vs_expense(self, user: Dict[str, Any], period: str = 'mensal', month: Optional[int] = None, year: Optional[int] = None) -> Dict[str, Any]:
        """
        Gera dados para gráfico Receita vs Despesa no período (Chart.js).
        
        Agrupa transações por type (income/expense), soma os valores e calcula
        o resultado (receita - despesa). Usa a mesma lógica de período (_get_period_dates).
        
        Args:
            user: Documento do usuário MongoDB
            period: Período ('diário', 'semanal', 'mensal', 'anual')
            month: Mês (1-12) quando period mensal (opcional).
            year: Ano quando period mensal ou anual (opcional).
        
        Returns:
            Dict com labels ["Receita", "Despesa"], datasets e campo "resultado"
        """
        scope, _ = resolve_user_read_scope(user)
        start_date, end_date = self._get_period_dates(period, month, year)
        
        pipeline = [
            _EFFECTIVE_DATE_STAGE,
            {
                '$match': {
                    **scope,
                    '_effective_date': {'$gte': start_date, '$lte': end_date}
                }
            },
            {
                '$group': {
                    '_id': '$type',
                    'total': {'$sum': '$value'}
                }
            }
        ]
        
        results = list(self.transaction_repo.collection.aggregate(pipeline))
        
        income_total = 0.0
        expense_total = 0.0
        for r in results:
            tipo = r.get('_id')
            total = float(r.get('total', 0))
            if tipo == 'income':
                income_total = total
            elif tipo == 'expense':
                expense_total = total
        
        resultado = income_total - expense_total
        
        return {
            'labels': ['Receita', 'Despesa'],
            'datasets': [{
                'data': [income_total, expense_total],
                'backgroundColor': [
                    'rgba(34,197,94,0.8)',
                    'rgba(239,68,68,0.8)'
                ],
                'borderWidth': 1
            }],
            'resultado': resultado
        }
    
    def get_all_charts_data(self, user: Dict[str, Any], period: str = 'mensal', month: Optional[int] = None, year: Optional[int] = None) -> Dict[str, Any]:
        """
        Gera todos os dados de gráficos de uma vez.
        
        Args:
            user: Documento do usuário MongoDB
            period: Período ('diário', 'semanal', 'mensal', 'anual')
            month: Mês (1-12) quando period mensal (opcional, da query string).
            year: Ano quando period mensal ou anual (opcional, da query string).
        
        Returns:
            Dict com todos os dados de gráficos:
            {
                'by_category': {...},
                'by_weekday': {...},
                'by_hour': {...},
                'by_date': {...},
                'expenses_distribution': {...},
                'expenses_by_account': {...},
                'income_vs_expense': {...}
            }
        """
        return {
            'by_category': self.get_expenses_by_category_chart_data(user, period, month, year),
            'by_weekday': self.get_expenses_by_weekday_chart_data(user, period, month, year),
            'by_hour': self.get_expenses_by_hour_chart_data(user, period, month, year),
            'by_date': self.get_chart_data_by_date(user, period, month, year),
            'expenses_distribution': self.get_expenses_distribution(user, period, month, year),
            'expenses_by_account': self.get_expenses_by_account(user, period, month, year),
            'income_vs_expense': self.get_income_vs_expense(user, period, month, year)
        }

