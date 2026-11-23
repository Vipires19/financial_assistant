"""
Decorator para auditoria e logging.

Localização: core/decorators/audit_log.py

Decorator para logar ações automaticamente.
"""
from functools import wraps
from typing import Callable
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
