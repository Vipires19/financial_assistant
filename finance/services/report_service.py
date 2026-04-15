"""
Service para geração de relatórios financeiros.

Localização: finance/services/report_service.py

Este service gera relatórios textuais do período selecionado.
Estruturado para facilitar futuras integrações com IA e geração de PDF.
"""
from typing import Dict, Any, Optional, Mapping
from datetime import datetime
from finance.services.dashboard_service import DashboardService
from core.services.audit_log_service import AuditLogService


class ReportService:
    """
    Service para gerar relatórios financeiros.
    
    Estruturado para facilitar:
    - Integração com IA (análise automática)
    - Geração de PDF
    - Exportação em diferentes formatos
    """
    
    def __init__(self):
        self.dashboard_service = DashboardService()
        self.audit_service = AuditLogService()
    
    def generate_text_report(self, user: Mapping[str, Any], period: str = 'mensal') -> Dict[str, Any]:
        """
        Gera relatório textual do período.
        
        Args:
            user: Documento do usuário MongoDB (escopo de leitura: família quando aplicável)
            period: Período ('diário', 'semanal', 'mensal')
        
        Returns:
            Dict com:
            - report_text: Texto do relatório
            - metadata: Metadados (período, data de geração, etc.)
            - summary: Resumo numérico
        """
        try:
            user_id = str(user.get('_id', ''))
            # Busca dados do dashboard
            dashboard_data = self.dashboard_service.get_dashboard_data(user, period)
            
            # Gera texto do relatório
            report_text = self._build_report_text(dashboard_data, period)
            
            # Metadados
            metadata = {
                'period': period,
                'generated_at': datetime.utcnow().isoformat(),
                'user_id': user_id,
                'format': 'text'
            }
            
            # Resumo numérico
            summary = {
                'total_expenses': dashboard_data.get('total_expenses', 0),
                'total_income': dashboard_data.get('total_income', 0),
                'balance': dashboard_data.get('balance', 0),
                'transactions_count': len(dashboard_data.get('transactions', []))
            }
            
            result = {
                'report_text': report_text,
                'metadata': metadata,
                'summary': summary,
                'dashboard_data': dashboard_data  # Dados completos para futuras análises
            }
            
            # Loga geração de relatório bem-sucedida
            self.audit_service.log_report(
                user_id=user_id,
                report_type='text',
                source='dashboard',
                status='success',
                payload={
                    'period': period,
                    'format': 'text'
                }
            )
            
            return result
            
        except Exception as e:
            # Loga erro na geração
            self.audit_service.log_report(
                user_id=str(user.get('_id', '')),
                report_type='text',
                source='dashboard',
                status='error',
                error=str(e),
                payload={'period': period}
            )
            raise
    
    def _build_report_text(self, dashboard_data: Dict[str, Any], period: str) -> str:
        """
        Constrói o texto do relatório a partir dos dados do dashboard.
        
        Este método pode ser substituído por IA no futuro.
        
        Args:
            dashboard_data: Dados do dashboard
            period: Período do relatório
        
        Returns:
            String com o texto do relatório
        """
        period_names = {
            'diário': 'do dia',
            'semanal': 'da semana',
            'mensal': 'do mês'
        }
        period_name = period_names.get(period, 'do período')
        
        lines = []
        lines.append(f"📊 RELATÓRIO FINANCEIRO {period_name.upper()}")
        lines.append("=" * 50)
        lines.append("")
        
        # Resumo Financeiro
        lines.append("💰 RESUMO FINANCEIRO")
        lines.append("-" * 50)
        lines.append(f"Total de Entradas: R$ {dashboard_data.get('total_income', 0):.2f}")
        lines.append(f"Total de Gastos: R$ {dashboard_data.get('total_expenses', 0):.2f}")
        lines.append(f"Saldo: R$ {dashboard_data.get('balance', 0):.2f}")
        lines.append("")
        
        # Análises
        lines.append("📈 ANÁLISES")
        lines.append("-" * 50)
        
        # Dia com maior gasto
        day_expense = dashboard_data.get('day_with_highest_expense')
        if day_expense:
            lines.append(f"Dia com Maior Gasto: {day_expense.get('formatted_date', 'N/A')}")
            lines.append(f"  Valor: R$ {day_expense.get('total', 0):.2f}")
        else:
            lines.append("Dia com Maior Gasto: N/A")
        lines.append("")
        
        # Categoria com maior gasto
        cat_expense = dashboard_data.get('category_with_highest_expense')
        if cat_expense:
            lines.append(f"Categoria com Maior Gasto: {cat_expense.get('category', 'N/A')}")
            lines.append(f"  Valor: R$ {cat_expense.get('total', 0):.2f}")
            lines.append(f"  Transações: {cat_expense.get('count', 0)}")
        else:
            lines.append("Categoria com Maior Gasto: N/A")
        lines.append("")
        
        # Horário com maior gasto
        hour_expense = dashboard_data.get('hour_with_highest_expense')
        if hour_expense:
            lines.append(f"Horário com Maior Gasto: {hour_expense.get('formatted_hour', 'N/A')}")
            lines.append(f"  Valor: R$ {hour_expense.get('total', 0):.2f}")
            lines.append(f"  Transações: {hour_expense.get('count', 0)}")
        else:
            lines.append("Horário com Maior Gasto: N/A")
        lines.append("")
        
        # Estatísticas
        transactions = dashboard_data.get('transactions', [])
        if transactions:
            lines.append("📋 ESTATÍSTICAS")
            lines.append("-" * 50)
            lines.append(f"Total de Transações: {len(transactions)}")
            
            # Conta por tipo
            income_count = sum(1 for t in transactions if t.get('type') == 'income')
            expense_count = sum(1 for t in transactions if t.get('type') == 'expense')
            lines.append(f"  Receitas: {income_count}")
            lines.append(f"  Despesas: {expense_count}")
            lines.append("")
        
        # Observações
        balance = dashboard_data.get('balance', 0)
        lines.append("💡 OBSERVAÇÕES")
        lines.append("-" * 50)
        if balance > 0:
            lines.append("✅ Saldo positivo! Você está no azul.")
        elif balance < 0:
            lines.append("⚠️ Saldo negativo. Atenção aos gastos!")
        else:
            lines.append("⚖️ Saldo zerado. Equilíbrio entre receitas e despesas.")
        lines.append("")
        
        # Rodapé
        lines.append("=" * 50)
        lines.append(f"Relatório gerado em: {datetime.utcnow().strftime('%d/%m/%Y %H:%M:%S')}")
        
        return "\n".join(lines)
    
    def generate_ai_report(self, user: Mapping[str, Any], period: str = 'mensal') -> Dict[str, Any]:
        """
        Gera relatório com análise de IA (futuro).
        
        Este método será implementado quando a integração com IA estiver pronta.
        Por enquanto, retorna o relatório textual padrão.
        
        Args:
            user: Documento do usuário MongoDB
            period: Período
        
        Returns:
            Dict com relatório e análise de IA
        """
        # Por enquanto, retorna relatório textual
        # TODO: Integrar com IA para análise mais profunda
        report = self.generate_text_report(user, period)
        
        # Placeholder para análise de IA
        report['ai_analysis'] = {
            'enabled': False,
            'insights': [],
            'recommendations': []
        }
        
        return report
    
    def generate_pdf_report(self, user: Mapping[str, Any], period: str = 'mensal') -> bytes:
        """
        Gera relatório em PDF (futuro).
        
        Este método será implementado quando a geração de PDF estiver pronta.
        
        Args:
            user: Documento do usuário MongoDB
            period: Período
        
        Returns:
            Bytes do PDF gerado
        
        Raises:
            NotImplementedError: Por enquanto não implementado
        """
        # TODO: Implementar geração de PDF usando reportlab ou weasyprint
        raise NotImplementedError("Geração de PDF será implementada em breve")
    
    def generate_report(self, user: Mapping[str, Any], period: str = 'mensal', 
                       format: str = 'text', use_ai: bool = False) -> Dict[str, Any]:
        """
        Método principal para gerar relatórios.
        
        Args:
            user: Documento do usuário MongoDB
            period: Período
            format: Formato ('text', 'json', 'pdf')
            use_ai: Se deve usar IA para análise
        
        Returns:
            Dict ou bytes dependendo do formato
        """
        if format == 'pdf':
            return self.generate_pdf_report(user, period)
        
        if use_ai:
            report = self.generate_ai_report(user, period)
        else:
            report = self.generate_text_report(user, period)
        
        if format == 'json':
            return report
        
        # format == 'text'
        return {
            'report': report['report_text'],
            'metadata': report['metadata'],
            'summary': report['summary']
        }

