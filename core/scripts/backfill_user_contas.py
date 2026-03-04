"""
Migração: adiciona user.contas (contas padrão) a usuários que ainda não têm o campo.

Uso no Django shell:
    python manage.py shell
    >>> from core.scripts.backfill_user_contas import run
    >>> run()
"""
from core.database import get_database


DEFAULT_ACCOUNTS = [
    {
        "id": "conta_principal",
        "nome": "Conta Principal",
        "tipo": "bank",
        "saldo_inicial": 0,
        "ativa": True,
    },
    {
        "id": "dinheiro",
        "nome": "Dinheiro",
        "tipo": "cash",
        "saldo_inicial": 0,
        "ativa": True,
    },
]


def run():
    db = get_database()
    users = db.users
    result = users.update_many(
        {"contas": {"$exists": False}},
        {"$set": {"contas": DEFAULT_ACCOUNTS}},
    )
    print(f"Migração de contas concluída. Documentos modificados: {result.modified_count}")
    return result.modified_count
