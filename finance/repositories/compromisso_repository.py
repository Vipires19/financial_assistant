"""
Repository para compromissos.

Localização: finance/repositories/compromisso_repository.py

Gerencia operações CRUD de compromissos no MongoDB.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
from bson import ObjectId
from core.repositories.base_repository import BaseRepository
from pymongo.collection import Collection


class CompromissoRepository(BaseRepository):
    """
    Repository para gerenciar compromissos no MongoDB.
    
    Schema:
    {
        "_id": ObjectId,
        "user_id": ObjectId,
        "titulo": str,
        "descricao": str,
        "data": datetime,
        "hora": str,  # Formato HH:MM
        "tipo": str,  # Opcional: "Reunião", "Serviço", etc.
        "status": str,  # "pendente", "confirmado", "concluido", "cancelado"
        "created_at": datetime,
        "updated_at": datetime
    }
    """
    
    def __init__(self):
        # Usar a mesma conexão do BaseRepository
        # O BaseRepository já gerencia a conexão MongoDB
        super().__init__('compromissos')
    
    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cria um novo compromisso.
        
        Args:
            data: Dict com dados do compromisso (user_id, titulo, descricao, data, hora, tipo)
        
        Returns:
            Dict com o compromisso criado (incluindo _id)
        """
        # Garantir que user_id seja ObjectId
        if 'user_id' in data:
            data['user_id'] = ObjectId(data['user_id']) if not isinstance(data['user_id'], ObjectId) else data['user_id']
        
        # Adicionar campos padrão
        data['status'] = data.get('status', 'pendente')
        data['created_at'] = datetime.utcnow()
        data['updated_at'] = datetime.utcnow()
        
        # Converter data se for string
        if 'data' in data and isinstance(data['data'], str):
            try:
                data['data'] = datetime.strptime(data['data'], '%Y-%m-%d')
            except:
                data['data'] = datetime.strptime(data['data'], '%Y-%m-%d %H:%M:%S')
        
        result = self.collection.insert_one(data)
        return self.find_by_id(str(result.inserted_id))
    
    def find_by_user_and_period(self, user_id: str, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """
        Busca compromissos de um usuário em um período.
        
        Args:
            user_id: ID do usuário
            start_date: Data inicial
            end_date: Data final
        
        Returns:
            Lista de compromissos
        """
        # Garantir que as datas sejam naive (sem timezone) para MongoDB
        if start_date.tzinfo:
            start_date = start_date.astimezone().replace(tzinfo=None)
        if end_date.tzinfo:
            end_date = end_date.astimezone().replace(tzinfo=None)
        
        query = {
            'user_id': ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id,
            'data': {
                '$gte': start_date,
                '$lte': end_date
            }
        }
        
        try:
            compromissos = list(self.collection.find(query).sort('data', 1))
            return compromissos
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"[COMPROMISSO_REPO] Erro ao buscar compromissos: {e}", exc_info=True)
            raise
    
    def find_by_user(self, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Busca todos os compromissos de um usuário.
        
        Args:
            user_id: ID do usuário
            limit: Limite de resultados
        
        Returns:
            Lista de compromissos
        """
        query = {
            'user_id': ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
        }
        
        return list(self.collection.find(query).sort('data', 1).limit(limit))
    
    def update(self, compromisso_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Atualiza um compromisso.
        
        Args:
            compromisso_id: ID do compromisso
            data: Dict com campos a atualizar
        
        Returns:
            Compromisso atualizado ou None se não encontrado
        """
        # Converter data se for string
        if 'data' in data and isinstance(data['data'], str):
            try:
                data['data'] = datetime.strptime(data['data'], '%Y-%m-%d')
            except:
                data['data'] = datetime.strptime(data['data'], '%Y-%m-%d %H:%M:%S')
        
        data['updated_at'] = datetime.utcnow()
        
        result = self.collection.update_one(
            {'_id': ObjectId(compromisso_id)},
            {'$set': data}
        )
        
        if result.modified_count > 0:
            return self.find_by_id(compromisso_id)
        return None
    
    def delete(self, compromisso_id: str) -> bool:
        """
        Exclui um compromisso.
        
        Args:
            compromisso_id: ID do compromisso
        
        Returns:
            True se excluído com sucesso
        """
        result = self.collection.delete_one({'_id': ObjectId(compromisso_id)})
        return result.deleted_count > 0
