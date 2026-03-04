"""
Modelo de Conta Financeira (Django ORM).

Localização: finance/models/account_model.py

Representa contas financeiras do usuário (banco, dinheiro, cartão, etc.).
Estrutura para uso futuro; não altera transações, dashboard nem API existente.
"""
import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings


ACCOUNT_TYPES = [
    ("bank", "Conta Bancária"),
    ("cash", "Dinheiro"),
    ("credit_card", "Cartão de Crédito"),
    ("investment", "Investimento"),
    ("other", "Outro"),
]


class FinancialAccount(models.Model):
    """
    Conta financeira do usuário (banco, dinheiro, cartão, investimento, etc.).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="accounts",
    )
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=ACCOUNT_TYPES)
    initial_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Conta financeira"
        verbose_name_plural = "Contas financeiras"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.user.email})"
