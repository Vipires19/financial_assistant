"""
Repository base para MongoDB.

Localização: core/repositories/base_repository.py

Este é um repository base que pode ser estendido por outros repositories
para compartilhar funcionalidades comuns.
"""
from typing import Optional, Dict, Any, List
from core.database import get_database
from bson import ObjectId


class BaseRepository:
    """
    Repository base com operações CRUD comuns.
    
    Exemplo de uso:
        class UserRepository(BaseRepository):
            def __init__(self):
                super().__init__('users')
    """
    
    def __init__(self, collection_name: str):
        """
        Inicializa o repository.
        
        Args:
            collection_name: Nome da collection no MongoDB
        """
        self.db = get_database()
        self.collection = self.db[collection_name]
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """
        Cria índices necessários.
        Deve ser sobrescrito nas classes filhas.
        """
        pass
    
    def find_by_id(self, document_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca documento por ID.
        
        Args:
            document_id: ID do documento (ObjectId como string)
        
        Returns:
            Dict com dados do documento ou None
        """
        try:
            return self.collection.find_one({'_id': ObjectId(document_id)})
        except:
            return None
    
    def find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Busca um documento por query.
        
        Args:
            query: Query do MongoDB
        
        Returns:
            Dict com dados do documento ou None
        """
        return self.collection.find_one(query)
    
    def find_many(self, query: Dict[str, Any] = None, 
                  limit: int = 100, skip: int = 0,
                  sort: tuple = None) -> List[Dict[str, Any]]:
        """
        Busca múltiplos documentos.
        
        Args:
            query: Query do MongoDB (None para todos)
            limit: Limite de resultados
            skip: Quantidade a pular
            sort: Tupla (campo, direção) para ordenação
        
        Returns:
            Lista de documentos
        """
        cursor = self.collection.find(query or {})
        
        if sort:
            cursor = cursor.sort(sort[0], sort[1])
        
        cursor = cursor.skip(skip).limit(limit)
        return list(cursor)
    
    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cria um novo documento.
        
        Args:
            data: Dados do documento
        
        Returns:
            Dict com dados do documento criado (incluindo _id)
        """
        result = self.collection.insert_one(data)
        data['_id'] = result.inserted_id
        return data
    
    def update(self, document_id: str, data: Dict[str, Any]) -> bool:
        """
        Atualiza um documento.
        
        Args:
            document_id: ID do documento
            data: Dados a atualizar
        
        Returns:
            True se atualizado com sucesso
        """
        try:
            result = self.collection.update_one(
                {'_id': ObjectId(document_id)},
                {'$set': data}
            )
            return result.modified_count > 0
        except:
            return False
    
    def delete(self, document_id: str) -> bool:
        """
        Deleta um documento.
        
        Args:
            document_id: ID do documento
        
        Returns:
            True se deletado com sucesso
        """
        try:
            result = self.collection.delete_one({'_id': ObjectId(document_id)})
            return result.deleted_count > 0
        except:
            return False
    
    def count(self, query: Dict[str, Any] = None) -> int:
        """
        Conta documentos.
        
        Args:
            query: Query do MongoDB (None para todos)
        
        Returns:
            Número de documentos
        """
        return self.collection.count_documents(query or {})

