"""
Service para logs de auditoria.

Localização: core/services/audit_log_service.py

Este service gerencia a criação e consulta de logs de auditoria.
"""
from typing import Optional, Dict, Any, List
import traceback
from core.repositories.audit_log_repository import AuditLogRepository


class AuditLogService:
    """
    Service para gerenciar logs de auditoria.
    
    Exemplo de uso:
        service = AuditLogService()
        service.log_action(
            user_id='...',
            action='login',
            entity='user',
            source='dashboard',
            status='success'
        )
    """
    
    def __init__(self):
        self.audit_repo = AuditLogRepository()
    
    def log_action(self, user_id: Optional[str], action: str, entity: str,
                  source: str = 'dashboard', status: str = 'success',
                  entity_id: Optional[str] = None, payload: Optional[Dict[str, Any]] = None,
                  error: Optional[str] = None) -> Dict[str, Any]:
        """
        Registra uma ação no log de auditoria.
        
        Args:
            user_id: ID do usuário (None para ações do sistema)
            action: Tipo de ação ('login', 'create_transaction', 'generate_report', 'error')
            entity: Entidade relacionada ('user', 'transaction', 'report', 'system')
            source: Origem da ação ('dashboard', 'api', 'agent')
            status: Status da ação ('success', 'error')
            entity_id: ID da entidade (opcional)
            payload: Dados adicionais (opcional)
            error: Mensagem de erro ou stacktrace (opcional)
        
        Returns:
            Dict com dados do log criado
        """
        log_data = {
            'user_id': user_id,
            'action': action,
            'entity': entity,
            'source': source,
            'status': status,
        }
        
        if entity_id:
            log_data['entity_id'] = entity_id
        
        if payload:
            log_data['payload'] = payload
        
        if error:
            log_data['error'] = self._format_error(error)
        
        return self.audit_repo.create(log_data)
    
    def log_login(self, user_id: str, source: str = 'dashboard',
                 status: str = 'success', error: Optional[str] = None) -> Dict[str, Any]:
        """
        Registra tentativa de login.
        
        Args:
            user_id: ID do usuário
            source: Origem ('dashboard', 'api')
            status: 'success' ou 'error'
            error: Mensagem de erro (se status = 'error')
        
        Returns:
            Dict com dados do log criado
        """
        return self.log_action(
            user_id=user_id,
            action='login',
            entity='user',
            entity_id=user_id,
            source=source,
            status=status,
            error=error
        )
    
    def log_transaction(self, user_id: str, action: str, transaction_id: str,
                       source: str = 'dashboard', status: str = 'success',
                       payload: Optional[Dict[str, Any]] = None,
                       error: Optional[str] = None) -> Dict[str, Any]:
        """
        Registra ação relacionada a transação.
        
        Args:
            user_id: ID do usuário
            action: Tipo de ação ('create_transaction', 'update_transaction', 'delete_transaction')
            transaction_id: ID da transação
            source: Origem
            status: 'success' ou 'error'
            payload: Dados adicionais da transação
            error: Mensagem de erro
        
        Returns:
            Dict com dados do log criado
        """
        return self.log_action(
            user_id=user_id,
            action=action,
            entity='transaction',
            entity_id=transaction_id,
            source=source,
            status=status,
            payload=payload,
            error=error
        )
    
    def log_report(self, user_id: str, report_type: str = 'text',
                  source: str = 'dashboard', status: str = 'success',
                  payload: Optional[Dict[str, Any]] = None,
                  error: Optional[str] = None) -> Dict[str, Any]:
        """
        Registra geração de relatório.
        
        Args:
            user_id: ID do usuário
            report_type: Tipo de relatório ('text', 'json', 'pdf')
            source: Origem
            status: 'success' ou 'error'
            payload: Dados adicionais (período, formato, etc.)
            error: Mensagem de erro
        
        Returns:
            Dict com dados do log criado
        """
        return self.log_action(
            user_id=user_id,
            action='generate_report',
            entity='report',
            source=source,
            status=status,
            payload={
                'report_type': report_type,
                **(payload or {})
            },
            error=error
        )
    
    def log_error(self, user_id: Optional[str], action: str, entity: str,
                 error: str, source: str = 'dashboard',
                 entity_id: Optional[str] = None,
                 payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Registra um erro.
        
        Args:
            user_id: ID do usuário (None para erros do sistema)
            action: Tipo de ação que causou o erro
            entity: Entidade relacionada
            error: Mensagem de erro ou stacktrace
            source: Origem
            entity_id: ID da entidade (opcional)
            payload: Dados adicionais (opcional)
        
        Returns:
            Dict com dados do log criado
        """
        return self.log_action(
            user_id=user_id,
            action='error',
            entity=entity,
            entity_id=entity_id,
            source=source,
            status='error',
            payload=payload,
            error=error
        )
    
    def get_user_logs(self, user_id: str, limit: int = 100,
                     skip: int = 0) -> List[Dict[str, Any]]:
        """
        Busca logs de um usuário.
        
        Args:
            user_id: ID do usuário
            limit: Limite de resultados
            skip: Quantidade a pular
        
        Returns:
            Lista de logs
        """
        return self.audit_repo.find_by_user(user_id, limit, skip)
    
    def get_errors(self, user_id: Optional[str] = None,
                  limit: int = 100, skip: int = 0) -> List[Dict[str, Any]]:
        """
        Busca logs de erro.
        
        Args:
            user_id: ID do usuário (opcional)
            limit: Limite de resultados
            skip: Quantidade a pular
        
        Returns:
            Lista de logs de erro
        """
        return self.audit_repo.find_errors(user_id, limit, skip)
    
    def _format_error(self, error: Any) -> str:
        """
        Formata erro para armazenamento (stacktrace resumido).
        
        Args:
            error: Exception, string ou qualquer objeto
        
        Returns:
            String formatada com stacktrace resumido
        """
        if isinstance(error, Exception):
            # Pega apenas as últimas 3 linhas do stacktrace
            tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
            # Limita a 500 caracteres
            error_str = ''.join(tb_lines[-3:])
            if len(error_str) > 500:
                error_str = error_str[:497] + '...'
            return error_str
        elif isinstance(error, str):
            # Limita strings a 500 caracteres
            return error[:500] if len(error) > 500 else error
        else:
            return str(error)[:500]

