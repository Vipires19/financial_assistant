"""
Services do app finance.

Localização: finance/services/

Services contêm a lógica de negócio da aplicação.
Eles:
- Orquestram chamadas a repositories
- Aplicam regras de negócio
- Validam dados
- Transformam dados entre camadas

NÃO devem acessar diretamente o MongoDB, apenas via repositories.
"""
from .transaction_service import TransactionService
from .dashboard_service import DashboardService
from .report_service import ReportService
from .categoria_service import CategoriaService

__all__ = ['TransactionService', 'DashboardService', 'ReportService', 'CategoriaService']

