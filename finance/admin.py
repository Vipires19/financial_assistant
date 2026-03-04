"""
Registro dos modelos do app finance no Django Admin.
"""
from django.contrib import admin
from .models import FinancialAccount


@admin.register(FinancialAccount)
class FinancialAccountAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "type",
        "user",
        "initial_balance",
        "is_active",
        "created_at",
    )
    list_filter = ("type", "is_active")
    search_fields = ("name", "user__email")
    readonly_fields = ("id", "created_at")
    ordering = ("-created_at",)
