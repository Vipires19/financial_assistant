"""
Signals do app finance.

Cria contas padrão automaticamente quando um novo usuário (Django User) é criado.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

from .models import FinancialAccount

User = get_user_model()


@receiver(post_save, sender=User)
def create_default_accounts(sender, instance, created, **kwargs):
    """
    Quando um novo usuário for criado, cria automaticamente duas contas:
    - Conta Principal (tipo bank, saldo inicial 0)
    - Dinheiro (tipo cash, saldo inicial 0)
    """
    if not created:
        return
    FinancialAccount.objects.create(
        user=instance,
        name="Conta Principal",
        type="bank",
        initial_balance=0,
    )
    FinancialAccount.objects.create(
        user=instance,
        name="Dinheiro",
        type="cash",
        initial_balance=0,
    )
