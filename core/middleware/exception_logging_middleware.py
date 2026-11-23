"""
Middleware para capturar e logar exceções não tratadas.

Localização: core/middleware/exception_logging_middleware.py

Este middleware captura exceções não tratadas e as registra no audit_log.
"""
import traceback
from core.services.audit_log_service import AuditLogService


class ExceptionLoggingMiddleware:
    """
    Middleware para capturar exceções não tratadas e logá-las.
    
    Deve ser adicionado após outros middlewares para capturar exceções.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.audit_service = AuditLogService()
    
    def __call__(self, request):
        response = self.get_response(request)
        return response
    
    def process_exception(self, request, exception):
        """
        Processa exceções não tratadas.
        
        Args:
            request: Request object
            exception: Exception capturada
        
        Returns:
            None (deixa Django tratar a exceção normalmente)
        """
        # Extrai user_id se disponível
        user_id = None
        if hasattr(request, 'user_mongo') and request.user_mongo:
            user_id = str(request.user_mongo['_id'])
        
        # Determina source baseado no path
        source = 'api' if request.path.startswith('/api/') or request.path.startswith('/finance/api/') else 'dashboard'
        
        # Formata stacktrace
        error_trace = traceback.format_exception(
            type(exception),
            exception,
            exception.__traceback__
        )
        error_str = ''.join(error_trace[-5:])  # Últimas 5 linhas
        if len(error_str) > 1000:
            error_str = error_str[:997] + '...'
        
        # Loga o erro
        try:
            self.audit_service.log_error(
                user_id=user_id,
                action='unhandled_exception',
                entity='system',
                error=error_str,
                source=source,
                payload={
                    'path': request.path,
                    'method': request.method,
                    'exception_type': type(exception).__name__,
                    'exception_message': str(exception)
                }
            )
        except:
            # Se falhar ao logar, não quebra o fluxo
            pass
        
        # Retorna None para deixar Django tratar a exceção normalmente
        return None

