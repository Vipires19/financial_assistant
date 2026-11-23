"""
Decorators do core.

Localização: core/decorators/

Decorators para autenticação e outras funcionalidades.
"""
from .audit_log import audit_log
from .auth import login_required_mongo