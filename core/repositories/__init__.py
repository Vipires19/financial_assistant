"""
Repositories do core.

Localização: core/repositories/

Repositories são a camada de acesso a dados (Data Access Layer).
Eles encapsulam todas as operações com MongoDB, isolando a lógica de acesso
a dados do resto da aplicação.

Estrutura:
- Cada repository representa uma collection do MongoDB
- Métodos CRUD básicos (create, read, update, delete)
- Queries específicas do domínio
- Validações básicas de dados
"""
from .user_repository import UserRepository
from .audit_log_repository import AuditLogRepository
from .update_repository import UpdateRepository

__all__ = ['UserRepository', 'AuditLogRepository', 'UpdateRepository']

