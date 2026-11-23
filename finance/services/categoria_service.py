"""
Service para gerenciar categorias personalizadas.

Localização: finance/services/categoria_service.py
"""
from typing import List, Dict, Any, Optional
from finance.repositories.categoria_repository import CategoriaRepository
from finance.models.categoria_model import CategoriaModel


class CategoriaService:
    """
    Service para gerenciar categorias personalizadas.
    """
    
    def __init__(self):
        self.categoria_repo = CategoriaRepository()
    
    def create_categoria(self, user_id: str, nome: str, tipo: str,
                        descricao: str = '') -> Dict[str, Any]:
        """
        Cria uma nova categoria personalizada.
        
        Args:
            user_id: ID do usuário
            nome: Nome da categoria
            tipo: Tipo da categoria
            descricao: Descrição (opcional)
        
        Returns:
            Dict com dados da categoria criada
        
        Raises:
            ValueError: Se dados inválidos
        """
        if not user_id:
            raise ValueError("user_id é obrigatório")
        
        if not nome or not nome.strip():
            raise ValueError("Nome da categoria é obrigatório")
        
        if not tipo or not tipo.strip():
            raise ValueError("Tipo da categoria é obrigatório")
        
        # Verifica se já existe categoria com mesmo nome para o usuário
        existing = self.categoria_repo.find_by_user(user_id)
        for cat in existing:
            if cat['nome'].lower() == nome.strip().lower():
                raise ValueError(f"Categoria '{nome}' já existe")
        
        categoria_data = CategoriaModel.create_categoria_data(
            user_id=user_id,
            nome=nome,
            tipo=tipo,
            descricao=descricao
        )
        
        return self.categoria_repo.create(categoria_data)
    
    def get_categorias_usuario(self, user_id: str, tipo: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Busca categorias de um usuário.
        
        Args:
            user_id: ID do usuário
            tipo: Tipo de categoria (opcional)
        
        Returns:
            Lista de categorias
        """
        if not user_id:
            raise ValueError("user_id é obrigatório")
        
        return self.categoria_repo.find_by_user(user_id, tipo)
    
    def delete_categoria(self, categoria_id: str, user_id: str) -> bool:
        """
        Deleta uma categoria.
        
        Args:
            categoria_id: ID da categoria
            user_id: ID do usuário
        
        Returns:
            True se deletado com sucesso
        
        Raises:
            ValueError: Se categoria não encontrada ou não pertence ao usuário
        """
        if not user_id:
            raise ValueError("user_id é obrigatório")
        
        categoria = self.categoria_repo.find_by_id(categoria_id, user_id)
        if not categoria:
            raise ValueError("Categoria não encontrada ou não pertence ao usuário")
        
        return self.categoria_repo.delete_by_id(categoria_id, user_id)
    
    def popular_categorias_predefinidas(self, user_id: str) -> List[str]:
        """
        Popula categorias pré-definidas para um novo usuário.
        
        Args:
            user_id: ID do usuário
        
        Returns:
            Lista de IDs das categorias criadas
        """
        if not user_id:
            raise ValueError("user_id é obrigatório")
        
        categorias_predefinidas = CategoriaModel.get_categorias_predefinidas()
        categorias_data = []
        
        for tipo, nomes in categorias_predefinidas.items():
            for nome in nomes:
                categorias_data.append(
                    CategoriaModel.create_categoria_data(
                        user_id=user_id,
                        nome=nome,
                        tipo=tipo,
                        descricao=''
                    )
                )
        
        return self.categoria_repo.create_many(categorias_data)
    
    def get_categorias_por_tipo(self, user_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Busca categorias agrupadas por tipo.
        
        Args:
            user_id: ID do usuário
        
        Returns:
            Dict com categorias agrupadas por tipo
        """
        categorias = self.get_categorias_usuario(user_id)
        
        categorias_por_tipo = {}
        for cat in categorias:
            tipo = cat.get('tipo', 'outros')
            if tipo not in categorias_por_tipo:
                categorias_por_tipo[tipo] = []
            categorias_por_tipo[tipo].append(cat)
        
        return categorias_por_tipo
