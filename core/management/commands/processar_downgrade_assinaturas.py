"""
Cron / agendador: downgrade automático após término do grace period.

Ex.: python manage.py processar_downgrade_assinaturas

Localização: core/management/commands/processar_downgrade_assinaturas.py
"""
from django.core.management.base import BaseCommand

from core.services.subscription_lifecycle_service import processar_downgrades_pendentes


class Command(BaseCommand):
    help = "Processa usuários com cancelamento agendado e data_fim_acesso no passado (downgrade para individual)."

    def handle(self, *args, **options):
        n = processar_downgrades_pendentes()
        self.stdout.write(self.style.SUCCESS(f"Downgrades aplicados: {n}"))
