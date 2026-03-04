"""
Service para gerenciar categorias personalizadas do usuário.

Localização: core/services/categoria_usuario_service.py

Este service gerencia as categorias armazenadas no campo JSONField
do documento do usuário no MongoDB.
"""
from typing import Dict, List, Any, Optional
from core.repositories.user_repository import UserRepository
from finance.models.categoria_model import CategoriaModel


class CategoriaUsuarioService:
    """
    Service para gerenciar categorias personalizadas do usuário.
    
    As categorias são armazenadas no campo 'categorias' do documento do usuário
    como um dicionário onde:
    - Chaves: tipos de categorias (ex: 'receita', 'alimentacao')
    - Valores: listas de nomes de categorias (ex: ['Salário', 'Aluguel'])
    """
    
    def __init__(self):
        self.user_repo = UserRepository()
    
    def get_categorias_usuario(self, user_id: str) -> Dict[str, List[str]]:
        """
        Busca todas as categorias do usuário.
        
        Args:
            user_id: ID do usuário
        
        Returns:
            Dict com categorias organizadas por tipo
        """
        if not user_id:
            raise ValueError("user_id é obrigatório")
        
        user = self.user_repo.find_by_id(user_id)
        if not user:
            raise ValueError("Usuário não encontrado")
        
        # Retorna categorias ou dicionário vazio se não existir
        return user.get('categorias', {})
    
    def get_categorias_por_tipo(self, user_id: str, tipo: str) -> List[str]:
        """
        Busca categorias de um tipo específico.
        
        Args:
            user_id: ID do usuário
            tipo: Tipo de categoria (ex: 'receita', 'alimentacao')
        
        Returns:
            Lista de nomes de categorias do tipo especificado
        """
        categorias = self.get_categorias_usuario(user_id)
        return categorias.get(tipo, [])
    
    def adicionar_categoria(self, user_id: str, tipo: str, nome: str) -> bool:
        """
        Adiciona uma nova categoria ao usuário.
        
        Args:
            user_id: ID do usuário
            tipo: Tipo de categoria
            nome: Nome da categoria
        
        Returns:
            True se adicionado com sucesso
        
        Raises:
            ValueError: Se categoria já existe ou dados inválidos
        """
        if not user_id or not tipo or not nome:
            raise ValueError("user_id, tipo e nome são obrigatórios")
        
        nome = nome.strip()
        if not nome:
            raise ValueError("Nome da categoria não pode ser vazio")
        
        user = self.user_repo.find_by_id(user_id)
        if not user:
            raise ValueError("Usuário não encontrado")
        
        # Obtém categorias atuais
        categorias = user.get('categorias', {})
        
        # Inicializa lista do tipo se não existir
        if tipo not in categorias:
            categorias[tipo] = []
        
        # Verifica se categoria já existe (case-insensitive)
        categorias_tipo = [c.lower() for c in categorias[tipo]]
        if nome.lower() in categorias_tipo:
            raise ValueError(f"Categoria '{nome}' já existe no tipo '{tipo}'")
        
        # Adiciona categoria
        categorias[tipo].append(nome)
        
        # Atualiza usuário
        self.user_repo.update(user_id, categorias=categorias)
        
        return True
    
    def remover_categoria(self, user_id: str, tipo: str, nome: str) -> bool:
        """
        Remove uma categoria do usuário.
        
        Args:
            user_id: ID do usuário
            tipo: Tipo de categoria
            nome: Nome da categoria
        
        Returns:
            True se removido com sucesso
        
        Raises:
            ValueError: Se categoria não encontrada
        """
        if not user_id or not tipo or not nome:
            raise ValueError("user_id, tipo e nome são obrigatórios")
        
        user = self.user_repo.find_by_id(user_id)
        if not user:
            raise ValueError("Usuário não encontrado")
        
        categorias = user.get('categorias', {})
        
        if tipo not in categorias:
            raise ValueError(f"Tipo '{tipo}' não encontrado")
        
        # Remove categoria (case-insensitive)
        categorias_tipo = categorias[tipo]
        categoria_encontrada = None
        for cat in categorias_tipo:
            if cat.lower() == nome.lower():
                categoria_encontrada = cat
                break
        
        if not categoria_encontrada:
            raise ValueError(f"Categoria '{nome}' não encontrada no tipo '{tipo}'")
        
        categorias[tipo].remove(categoria_encontrada)
        
        # Remove tipo se lista ficar vazia (opcional)
        # if not categorias[tipo]:
        #     del categorias[tipo]
        
        # Atualiza usuário
        self.user_repo.update(user_id, categorias=categorias)
        
        return True
    
    def editar_categoria(self, user_id: str, tipo: str, nome_antigo: str, nome_novo: str) -> bool:
        """
        Edita o nome de uma categoria.
        
        Args:
            user_id: ID do usuário
            tipo: Tipo de categoria
            nome_antigo: Nome atual da categoria
            nome_novo: Novo nome da categoria
        
        Returns:
            True se editado com sucesso
        
        Raises:
            ValueError: Se categoria não encontrada ou novo nome já existe
        """
        if not user_id or not tipo or not nome_antigo or not nome_novo:
            raise ValueError("Todos os parâmetros são obrigatórios")
        
        nome_novo = nome_novo.strip()
        if not nome_novo:
            raise ValueError("Novo nome não pode ser vazio")
        
        user = self.user_repo.find_by_id(user_id)
        if not user:
            raise ValueError("Usuário não encontrado")
        
        categorias = user.get('categorias', {})
        
        if tipo not in categorias:
            raise ValueError(f"Tipo '{tipo}' não encontrado")
        
        # Encontra categoria antiga
        categorias_tipo = categorias[tipo]
        indice = None
        for i, cat in enumerate(categorias_tipo):
            if cat.lower() == nome_antigo.lower():
                indice = i
                break
        
        if indice is None:
            raise ValueError(f"Categoria '{nome_antigo}' não encontrada no tipo '{tipo}'")
        
        # Verifica se novo nome já existe (exceto o próprio)
        categorias_lower = [c.lower() for c in categorias_tipo]
        if nome_novo.lower() in categorias_lower and categorias_tipo[indice].lower() != nome_novo.lower():
            raise ValueError(f"Categoria '{nome_novo}' já existe no tipo '{tipo}'")
        
        # Atualiza categoria
        categorias[tipo][indice] = nome_novo
        
        # Atualiza usuário
        self.user_repo.update(user_id, categorias=categorias)
        
        return True
    
    def get_todas_categorias_formatadas(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Retorna todas as categorias formatadas para uso em formulários.
        
        Args:
            user_id: ID do usuário
        
        Returns:
            Lista de dicts com {tipo, nome, label_tipo}
        """
        categorias = self.get_categorias_usuario(user_id)
        tipos_labels = {
            'receita': 'Receitas',
            'entrada': 'Outras Entradas',
            'investimento': 'Investimentos',
            'alimentacao': 'Alimentação',
            'transporte': 'Transporte',
            'saude': 'Saúde e Bem Estar',
            'lazer': 'Lazer',
            'educacao': 'Educação',
            'habitacao': 'Habitação',
            'outros': 'Demais Despesas'
        }
        
        todas_categorias = []
        for tipo, nomes in categorias.items():
            label_tipo = tipos_labels.get(tipo, tipo)
            for nome in nomes:
                todas_categorias.append({
                    'tipo': tipo,
                    'nome': nome,
                    'label_tipo': label_tipo,
                    'display': f"{nome} ({label_tipo})"
                })
        
        return todas_categorias
