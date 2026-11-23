"""
Repository para as novidades/updates do Leozera (changelog) no MongoDB.

Localização: core/repositories/update_repository.py

Schema da collection updates:
{
  _id: ObjectId,
  titulo: String,
  descricao: String,
  tipo: String,           // 'Nova funcionalidade' | 'Melhoria' | 'Correção de bug' | 'Atualização'
  data_publicacao: ISODate
}
"""
from typing import List, Dict, Any
from datetime import datetime
from core.repositories.base_repository import BaseRepository


# Tipos válidos de update (changelog)
UPDATE_TIPOS = [
    'Nova funcionalidade',
    'Melhoria',
    'Correção de bug',
    'Atualização',
]


class UpdateRepository(BaseRepository):
    """
    Repository para gerenciar updates (novidades) do Leozera no MongoDB.
    """

    def __init__(self):
        super().__init__('updates')

    def _ensure_indexes(self):
        """Índices para ordenação por data (mais recentes primeiro)."""
        self.collection.create_index('data_publicacao')

    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cria um novo update.

        Args:
            data: dict com titulo, descricao, tipo

        Returns:
            Dict do documento criado (incluindo _id e data_publicacao).
        """
        if 'data_publicacao' not in data:
            data['data_publicacao'] = datetime.utcnow()
        if data.get('tipo') not in UPDATE_TIPOS:
            data['tipo'] = 'Atualização'
        return super().create(data)

    def list_all_ordered(self, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Lista todos os updates ordenados do mais recente para o mais antigo.

        Returns:
            Lista de updates com data_publicacao em ordem decrescente.
        """
        return self.find_many(
            query={},
            limit=limit,
            skip=0,
            sort=('data_publicacao', -1)
        )
