"""
Repository para categorias personalizadas no MongoDB.

Localização: finance/repositories/categoria_repository.py
"""
from typing import Optional, List, Dict, Any
from core.repositories.base_repository import BaseRepository
from datetime import datetime
from bson import ObjectId


class CategoriaRepository(BaseRepository):
    """
    Repository para gerenciar categorias personalizadas no MongoDB.
    """
    
    def __init__(self):
        super().__init__('categorias')
    
    def _ensure_indexes(self):
        """
        Cria índices necessários para otimizar queries.
        """
        # Índice para user_id
        self.collection.create_index('user_id')
        
        # Índice composto para buscar por usuário e tipo
        self.collection.create_index([('user_id', 1), ('tipo', 1)])
        
        # Índice composto para buscar por usuário e nome
        self.collection.create_index([('user_id', 1), ('nome', 1)])
    
    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cria uma nova categoria.
        
        SEGURANÇA: Valida que user_id está presente.
        
        Args:
            data: Dados da categoria (deve conter 'user_id')
        
        Returns:
            Dict com dados da categoria criada
        """
        if 'user_id' not in data:
            raise ValueError("user_id é obrigatório para criar categoria")
        
        if isinstance(data['user_id'], str):
            data['user_id'] = ObjectId(data['user_id'])
        
        if 'created_at' not in data:
            data['created_at'] = datetime.utcnow()
        
        if 'updated_at' not in data:
            data['updated_at'] = datetime.utcnow()
        
        return super().create(data)
    
    def find_by_user(self, user_id: str, tipo: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Busca categorias de um usuário.
        
        SEGURANÇA: Sempre filtra por user_id.
        
        Args:
            user_id: ID do usuário
            tipo: Tipo de categoria (opcional)
        
        Returns:
            Lista de categorias
        """
        if not user_id:
            raise ValueError("user_id é obrigatório")
        
        query = {'user_id': ObjectId(user_id) if isinstance(user_id, str) else user_id}
        
        if tipo:
            query['tipo'] = tipo
        
        return self.find_many(
            query=query,
            sort=('nome', 1)  # Ordena por nome
        )
    
    def find_by_id(self, categoria_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Busca categoria por ID.
        
        SEGURANÇA: Se user_id fornecido, valida que pertence ao usuário.
        
        Args:
            categoria_id: ID da categoria
            user_id: ID do usuário (opcional, mas recomendado)
        
        Returns:
            Dict com dados da categoria ou None
        """
        try:
            query = {'_id': ObjectId(categoria_id)}
            
            if user_id:
                query['user_id'] = ObjectId(user_id) if isinstance(user_id, str) else user_id
            
            return self.collection.find_one(query)
        except:
            return None
    
    def delete_by_id(self, categoria_id: str, user_id: str) -> bool:
        """
        Deleta uma categoria.
        
        SEGURANÇA: Valida que categoria pertence ao usuário.
        
        Args:
            categoria_id: ID da categoria
            user_id: ID do usuário
        
        Returns:
            True se deletado com sucesso
        """
        if not user_id:
            raise ValueError("user_id é obrigatório")
        
        result = self.collection.delete_one({
            '_id': ObjectId(categoria_id),
            'user_id': ObjectId(user_id) if isinstance(user_id, str) else user_id
        })
        
        return result.deleted_count > 0
    
    def create_many(self, categorias: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Cria múltiplas categorias de uma vez.
        
        Args:
            categorias: Lista de dados de categorias
        
        Returns:
            Lista de IDs das categorias criadas
        """
        if not categorias:
            return []
        
        # Adiciona timestamps
        now = datetime.utcnow()
        for cat in categorias:
            if 'created_at' not in cat:
                cat['created_at'] = now
            if 'updated_at' not in cat:
                cat['updated_at'] = now
            if isinstance(cat.get('user_id'), str):
                cat['user_id'] = ObjectId(cat['user_id'])
        
        result = self.collection.insert_many(categorias)
        return [str(id) for id in result.inserted_ids]
