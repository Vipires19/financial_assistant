"""
Repository para logs de auditoria no MongoDB.

Localização: core/repositories/audit_log_repository.py

Schema da collection audit_logs:
{
  _id: ObjectId,
  user_id: ObjectId,
  action: String,              // 'login', 'create_transaction', 'generate_report', 'error'
  entity: String,              // 'user', 'transaction', 'report', 'system'
  entity_id: String,           // ID da entidade (opcional)
  payload: Object,             // Dados adicionais
  source: String,              // 'dashboard', 'api', 'agent'
  status: String,              // 'success', 'error'
  error: String,               // Stacktrace resumido (se status = 'error')
  created_at: ISODate
}
"""
from typing import Optional, List, Dict, Any
from core.repositories.base_repository import BaseRepository
from datetime import datetime
from bson import ObjectId


class AuditLogRepository(BaseRepository):
    """
    Repository para gerenciar logs de auditoria no MongoDB.
    
    Exemplo de uso:
        repo = AuditLogRepository()
        log = repo.create({
            'user_id': ObjectId('...'),
            'action': 'login',
            'entity': 'user',
            'source': 'dashboard',
            'status': 'success'
        })
    """
    
    def __init__(self):
        super().__init__('audit_logs')
    
    def _ensure_indexes(self):
        """
        Cria índices necessários para otimizar queries de auditoria.
        
        Índices:
        - user_id: Filtros por usuário
        - [user_id, created_at] (desc): Ordenação e filtros por período
        - action: Filtros por tipo de ação
        - [user_id, action]: Análises por usuário e ação
        - status: Filtros por status (sucesso/erro)
        - created_at: Filtros globais por data
        """
        # Índice simples para user_id
        self.collection.create_index('user_id')
        
        # Índice composto para ordenação por data (mais recentes primeiro)
        self.collection.create_index([('user_id', 1), ('created_at', -1)])
        
        # Índice simples para action
        self.collection.create_index('action')
        
        # Índice composto para análises por usuário e ação
        self.collection.create_index([('user_id', 1), ('action', 1)])
        
        # Índice simples para status
        self.collection.create_index('status')
        
        # Índice simples para created_at
        self.collection.create_index('created_at')
        
        # Índice composto para source
        self.collection.create_index('source')
    
    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cria um novo log de auditoria.
        
        Args:
            data: Dados do log
        
        Returns:
            Dict com dados do log criado (incluindo _id)
        """
        # Adiciona created_at se não fornecido
        if 'created_at' not in data:
            data['created_at'] = datetime.utcnow()
        
        # Converte user_id para ObjectId se for string
        if 'user_id' in data and isinstance(data['user_id'], str):
            try:
                data['user_id'] = ObjectId(data['user_id'])
            except:
                pass  # Mantém como string se não for ObjectId válido
        
        return super().create(data)
    
    def find_by_user(self, user_id: str, limit: int = 100, 
                     skip: int = 0) -> List[Dict[str, Any]]:
        """
        Busca logs de um usuário.
        
        Args:
            user_id: ID do usuário
            limit: Limite de resultados
            skip: Quantidade a pular
        
        Returns:
            Lista de logs ordenados por data (mais recentes primeiro)
        """
        query = {'user_id': ObjectId(user_id) if isinstance(user_id, str) else user_id}
        return self.find_many(
            query=query,
            limit=limit,
            skip=skip,
            sort=('created_at', -1)
        )
    
    def find_by_action(self, action: str, limit: int = 100,
                      skip: int = 0) -> List[Dict[str, Any]]:
        """
        Busca logs por tipo de ação.
        
        Args:
            action: Tipo de ação
            limit: Limite de resultados
            skip: Quantidade a pular
        
        Returns:
            Lista de logs
        """
        return self.find_many(
            query={'action': action},
            limit=limit,
            skip=skip,
            sort=('created_at', -1)
        )
    
    def find_errors(self, user_id: Optional[str] = None,
                   limit: int = 100, skip: int = 0) -> List[Dict[str, Any]]:
        """
        Busca apenas logs de erro.
        
        Args:
            user_id: ID do usuário (opcional, se None busca todos)
            limit: Limite de resultados
            skip: Quantidade a pular
        
        Returns:
            Lista de logs de erro
        """
        query = {'status': 'error'}
        if user_id:
            query['user_id'] = ObjectId(user_id) if isinstance(user_id, str) else user_id
        
        return self.find_many(
            query=query,
            limit=limit,
            skip=skip,
            sort=('created_at', -1)
        )

