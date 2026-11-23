"""
Service para lógica de autenticação.

Localização: core/services/auth_service.py

Este service contém a lógica de negócio relacionada a autenticação.
Ele usa o UserRepository para acessar dados, mas adiciona
validações e regras de negócio.
"""
from typing import Optional, Dict, Any
from core.repositories.user_repository import UserRepository


class AuthService:
    """
    Service para gerenciar autenticação de usuários.
    
    Exemplo de uso:
        service = AuthService()
        user = service.authenticate('user@email.com', 'senha123')
    """
    
    def __init__(self):
        self.user_repo = UserRepository()
    
    def register(self, email: str, password: str, **kwargs) -> Dict[str, Any]:
        """
        Registra um novo usuário.
        
        Args:
            email: Email do usuário
            password: Senha em texto plano
            **kwargs: Campos adicionais
        
        Returns:
            Dict com dados do usuário criado
        
        Raises:
            ValueError: Se email já existe ou dados inválidos
        """
        # Validações de negócio
        if not email or not email.strip():
            raise ValueError("Email é obrigatório")
        
        if not password or len(password) < 6:
            raise ValueError("Senha deve ter no mínimo 6 caracteres")
        
        # Verifica se email já existe
        existing_user = self.user_repo.find_by_email(email)
        if existing_user:
            raise ValueError("Email já cadastrado")
        
        # Cria usuário via repository
        # As categorias pré-definidas são populadas automaticamente no UserRepository.create()
        user = self.user_repo.create(email, password, **kwargs)
        
        return user
    
    def authenticate(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Autentica um usuário.
        
        Args:
            email: Email do usuário
            password: Senha em texto plano
        
        Returns:
            Dict com dados do usuário se autenticado, None caso contrário
        """
        if not email or not password:
            return None
        
        # Verifica senha via repository
        if self.user_repo.verify_password(email, password):
            user = self.user_repo.find_by_email(email)
            if user:
                # Remove senha do retorno e adiciona id como string
                user.pop('password_hash', None)
                user['id'] = str(user['_id'])
                return user
        
        return None
    
    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca usuário por ID.
        
        Args:
            user_id: ID do usuário
        
        Returns:
            Dict com dados do usuário ou None
        """
        user = self.user_repo.find_by_id(user_id)
        if user:
            user['id'] = str(user['_id'])
        return user

