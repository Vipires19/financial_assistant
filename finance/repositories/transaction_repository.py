"""
Repository para transações financeiras.

Localização: finance/repositories/transaction_repository.py

Este repository encapsula todas as operações com a collection 'transactions'
no MongoDB.

Schema da collection:
{
  _id: ObjectId,
  user_id: ObjectId,
  type: "expense" | "income",
  category: String,
  description: String,
  value: Number (sempre positivo),
  created_at: ISODate,
  hour: Number (0-23, extraído para análises),
  account_id: String | null (opcional, UUID da FinancialAccount)
}
"""
from typing import Optional, List, Dict, Any, Mapping
from core.repositories.base_repository import BaseRepository
from datetime import datetime
from bson import ObjectId


class TransactionRepository(BaseRepository):
    """
    Repository para gerenciar transações financeiras no MongoDB.
    
    Exemplo de uso:
        repo = TransactionRepository()
        transaction = repo.create({
            'user_id': ObjectId('...'),
            'type': 'expense',
            'category': 'Alimentação',
            'description': 'Almoço',
            'value': 45.50
        })
    """
    
    def __init__(self):
        super().__init__('transactions')
    
    def _ensure_indexes(self):
        """
        Cria índices necessários para otimizar queries.
        
        Índices:
        - user_id: Filtros por usuário
        - [user_id, created_at] (desc): Ordenação e filtros por período
        - created_at: Filtros globais por data
        - [user_id, type]: Filtros por tipo (receita/despesa)
        - [user_id, category]: Análises por categoria
        """
        # Índice simples para user_id
        self.collection.create_index('user_id')
        
        # Índice composto para ordenação por data (mais recentes primeiro)
        self.collection.create_index([('user_id', 1), ('created_at', -1)])
        
        # Índice simples para created_at (filtros globais)
        self.collection.create_index('created_at')
        
        # Índice composto para filtros por tipo
        self.collection.create_index([('user_id', 1), ('type', 1)])
        
        # Índice composto para análises por categoria
        self.collection.create_index([('user_id', 1), ('category', 1)])
    
    def find_by_user(self, user_id: str, limit: int = 100, 
                     skip: int = 0) -> List[Dict[str, Any]]:
        """
        Busca transações de um usuário.
        
        SEGURANÇA: Sempre filtra por user_id para garantir isolamento de dados.
        
        Args:
            user_id: ID do usuário (obrigatório)
            limit: Limite de resultados
            skip: Quantidade a pular
        
        Returns:
            Lista de transações ordenadas por created_at (mais recentes primeiro)
        
        Raises:
            ValueError: Se user_id não fornecido
        """
        if not user_id:
            raise ValueError("user_id é obrigatório para buscar transações")
        
        return self.find_many(
            query={'user_id': ObjectId(user_id)},
            limit=limit,
            skip=skip,
            sort=('created_at', -1)  # Usa created_at conforme schema
        )

    def find_by_read_scope(
        self, user: Mapping[str, Any], limit: int = 100, skip: int = 0
    ) -> List[Dict[str, Any]]:
        """Lista transações no escopo de leitura (família ou individual)."""
        from core.services.user_scope import get_user_scope_filter

        return self.find_many(
            query=get_user_scope_filter(user),
            limit=limit,
            skip=skip,
            sort=('created_at', -1),
        )
    
    def get_summary(self, user_id: str, start_date: Optional[datetime] = None,
                   end_date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Calcula resumo financeiro do usuário.
        
        SEGURANÇA: Sempre filtra por user_id para garantir isolamento de dados.
        
        Args:
            user_id: ID do usuário (obrigatório)
            start_date: Data inicial (opcional)
            end_date: Data final (opcional)
        
        Returns:
            Dict com resumo (total_income, total_expense, balance)
        
        Raises:
            ValueError: Se user_id não fornecido
        """
        if not user_id:
            raise ValueError("user_id é obrigatório para calcular resumo")
        
        query = {'user_id': ObjectId(user_id)}
        
        if start_date or end_date:
            date_query = {}
            if start_date:
                date_query['$gte'] = start_date
            if end_date:
                date_query['$lte'] = end_date
            query['created_at'] = date_query  # Usa created_at conforme schema
        
        pipeline = [
            {'$match': query},
            {
                '$group': {
                    '_id': '$type',
                    'total': {'$sum': '$value'}  # Usa value conforme schema
                }
            }
        ]
        
        results = list(self.collection.aggregate(pipeline))
        
        total_income = sum(r['total'] for r in results if r['_id'] == 'income')
        total_expense = sum(r['total'] for r in results if r['_id'] == 'expense')
        
        return {
            'total_income': total_income,
            'total_expense': total_expense,
            'balance': total_income - total_expense
        }
    
    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cria uma nova transação.
        
        SEGURANÇA: Valida que user_id está presente e é válido.
        
        Extrai automaticamente o campo 'hour' de 'created_at' se não fornecido.
        
        Args:
            data: Dados da transação (deve conter 'user_id')
        
        Returns:
            Dict com dados da transação criada (incluindo _id)
        
        Raises:
            ValueError: Se user_id não fornecido ou inválido
        """
        # Validação de segurança: user_id obrigatório
        if 'user_id' not in data:
            raise ValueError("user_id é obrigatório para criar transação")
        
        # Converte user_id para ObjectId se for string
        if isinstance(data['user_id'], str):
            try:
                data['user_id'] = ObjectId(data['user_id'])
            except:
                raise ValueError("user_id inválido")
        
        # Se created_at não foi fornecido, usa agora
        if 'created_at' not in data:
            data['created_at'] = datetime.utcnow()
        
        # Extrai hour de created_at se não fornecido
        if 'hour' not in data and 'created_at' in data:
            if isinstance(data['created_at'], datetime):
                data['hour'] = data['created_at'].hour
            else:
                # Se for string, tenta converter
                try:
                    if isinstance(data['created_at'], str):
                        from dateutil import parser
                        dt = parser.parse(data['created_at'])
                    else:
                        dt = data['created_at']
                    data['hour'] = dt.hour
                except:
                    data['hour'] = datetime.utcnow().hour
        
        # Garante que value é sempre positivo
        if 'value' in data:
            data['value'] = abs(float(data['value']))

        # account_id opcional (UUID da conta financeira como string)
        if 'account_id' in data and data['account_id'] is not None:
            data['account_id'] = str(data['account_id']).strip() or None
        elif 'account_id' not in data:
            data['account_id'] = None
        
        return super().create(data)
