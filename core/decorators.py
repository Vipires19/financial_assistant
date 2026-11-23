"""
Decorators para auditoria e logging.

Localização: core/decorators.py

Decorators para logar ações automaticamente.
"""
from functools import wraps
from typing import Callable, Any, Optional
from core.services.audit_log_service import AuditLogService
import traceback


def audit_log(action: str, entity: str, source: str = 'api'):
    """
    Decorator para logar ações automaticamente.
    
    Args:
        action: Tipo de ação ('create_transaction', 'generate_report', etc.)
        entity: Entidade relacionada ('transaction', 'report', etc.)
        source: Origem ('dashboard', 'api', 'agent')
    
    Exemplo de uso:
        @audit_log(action='create_transaction', entity='transaction', source='api')
        def create_transaction_view(request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            audit_service = AuditLogService()
            user_id = None
            entity_id = None
            payload = {}
            status = 'success'
            error = None
            
            # Tenta extrair user_id do request (primeiro argumento se for view)
            if args and hasattr(args[0], 'user_mongo'):
                request = args[0]
                if hasattr(request, 'user_mongo') and request.user_mongo:
                    user_id = str(request.user_mongo['_id'])
            
            # Tenta extrair entity_id dos kwargs ou args
            if 'transaction_id' in kwargs:
                entity_id = kwargs['transaction_id']
            elif 'user_id' in kwargs:
                entity_id = kwargs['user_id']
            
            # Tenta extrair payload dos kwargs
            if 'payload' in kwargs:
                payload = kwargs['payload']
            
            try:
                # Executa a função
                result = func(*args, **kwargs)
                
                # Se result tiver entity_id, usa ele
                if isinstance(result, dict) and 'id' in result:
                    entity_id = result['id']
                
                # Log de sucesso
                audit_service.log_action(
                    user_id=user_id,
                    action=action,
                    entity=entity,
                    entity_id=entity_id,
                    source=source,
                    status='success',
                    payload=payload
                )
                
                return result
                
            except Exception as e:
                # Log de erro
                error = traceback.format_exc()
                audit_service.log_error(
                    user_id=user_id,
                    action=action,
                    entity=entity,
                    error=error,
                    source=source,
                    entity_id=entity_id,
                    payload=payload
                )
                
                # Re-raise a exceção
                raise
        
        return wrapper
    return decorator


def log_action(action: str, entity: str, source: str = 'api',
              get_user_id: Optional[Callable] = None,
              get_entity_id: Optional[Callable] = None,
              get_payload: Optional[Callable] = None):
    """
    Decorator mais flexível para logar ações.
    
    Args:
        action: Tipo de ação
        entity: Entidade relacionada
        source: Origem
        get_user_id: Função para extrair user_id (recebe *args, **kwargs)
        get_entity_id: Função para extrair entity_id (recebe *args, **kwargs)
        get_payload: Função para extrair payload (recebe *args, **kwargs)
    
    Exemplo de uso:
        @log_action(
            action='create_transaction',
            entity='transaction',
            get_user_id=lambda req, *a, **kw: str(req.user_mongo['_id']),
            get_entity_id=lambda *a, **kw: kw.get('transaction_id')
        )
        def create_transaction(request, transaction_id):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            audit_service = AuditLogService()
            
            # Extrai dados usando funções fornecidas ou padrão
            if get_user_id:
                user_id = get_user_id(*args, **kwargs)
            elif args and hasattr(args[0], 'user_mongo'):
                request = args[0]
                user_id = str(request.user_mongo['_id']) if hasattr(request, 'user_mongo') and request.user_mongo else None
            else:
                user_id = None
            
            entity_id = get_entity_id(*args, **kwargs) if get_entity_id else None
            payload = get_payload(*args, **kwargs) if get_payload else {}
            
            status = 'success'
            error = None
            
            try:
                result = func(*args, **kwargs)
                
                # Log de sucesso
                audit_service.log_action(
                    user_id=user_id,
                    action=action,
                    entity=entity,
                    entity_id=entity_id,
                    source=source,
                    status='success',
                    payload=payload
                )
                
                return result
                
            except Exception as e:
                error = traceback.format_exc()
                audit_service.log_error(
                    user_id=user_id,
                    action=action,
                    entity=entity,
                    error=error,
                    source=source,
                    entity_id=entity_id,
                    payload=payload
                )
                raise
        
        return wrapper
    return decorator

