"""
Middleware de segurança para garantir isolamento de dados.

Localização: core/middleware/security_middleware.py

Este middleware garante que o user_id está sempre disponível no request
e valida permissões quando necessário.
"""
from typing import Optional


class SecurityMiddleware:
    """
    Middleware de segurança para controle multi-usuário.
    
    Garante:
    - user_id sempre disponível em request.user_id
    - Isolamento de dados entre usuários
    - Validação de permissões (futuro)
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Injeta user_id no request se usuário autenticado
        if hasattr(request, 'user_mongo') and request.user_mongo:
            request.user_id = str(request.user_mongo['_id'])
            request.user_role = request.user_mongo.get('role', 'user')
            request.user_account_id = request.user_mongo.get('account_id')
        else:
            request.user_id = None
            request.user_role = None
            request.user_account_id = None
        
        response = self.get_response(request)
        return response
    
    def get_user_id(self, request) -> Optional[str]:
        """
        Retorna user_id do request de forma segura.
        
        Args:
            request: Request object
        
        Returns:
            user_id como string ou None
        """
        if hasattr(request, 'user_id'):
            return request.user_id
        if hasattr(request, 'user_mongo') and request.user_mongo:
            return str(request.user_mongo['_id'])
        return None
    
    def require_user_id(self, request) -> str:
        """
        Retorna user_id ou levanta exceção se não autenticado.
        
        Args:
            request: Request object
        
        Returns:
            user_id como string
        
        Raises:
            ValueError: Se usuário não autenticado
        """
        user_id = self.get_user_id(request)
        if not user_id:
            raise ValueError("Usuário não autenticado")
        return user_id

