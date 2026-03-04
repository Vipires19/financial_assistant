"""
Backfill: adiciona account_id "legacy" em transações antigas (sem account_id).
Para cada usuário que possui transações sem account_id:
- Cria a conta "legacy" em user.contas (apenas se ainda não existir).
- Atualiza todas as transações desse usuário sem account_id para account_id: "legacy".

Uso:
    Na raiz do projeto (financeiro): python agent_ia/scripts/backfill_account_id.py

Ou no Django shell:
    python manage.py shell
    >>> from agent_ia.scripts.backfill_account_id import run_backfill
    >>> run_backfill()
"""
import os
import sys

# Permite rodar como script: python backfill_account_id.py (a partir da raiz: python agent_ia/scripts/backfill_account_id.py)
if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
    django.setup()

from core.database import get_database

LEGACY_ACCOUNT = {
    "id": "legacy",
    "nome": "Histórico Anterior à Organização por Contas",
    "tipo": "other",
    "saldo_inicial": 0,
    "ativa": False,
}


def run_backfill():
    db = get_database()
    coll_clientes = db.users
    coll_transacoes = db.transactions

    # user_ids que possuem ao menos uma transação sem account_id
    pipeline = [
        {"$match": {"account_id": {"$exists": False}}},
        {"$group": {"_id": "$user_id"}},
    ]
    user_ids = [doc["_id"] for doc in coll_transacoes.aggregate(pipeline)]

    usuarios_atualizados = 0
    transacoes_atualizadas = 0

    for user_id in user_ids:
        user_doc = coll_clientes.find_one({"_id": user_id})
        if not user_doc:
            continue

        contas = user_doc.get("contas", [])
        has_legacy = any(c.get("id") == "legacy" for c in contas)

        if not has_legacy:
            new_contas = list(contas)
            new_contas.append(LEGACY_ACCOUNT)
            coll_clientes.update_one(
                {"_id": user_id},
                {"$set": {"contas": new_contas}},
            )
            usuarios_atualizados += 1

        result = coll_transacoes.update_many(
            {"user_id": user_id, "account_id": {"$exists": False}},
            {"$set": {"account_id": "legacy"}},
        )
        transacoes_atualizadas += result.modified_count

    print("--- Backfill account_id (legacy) ---")
    print(f"Usuários atualizados: {usuarios_atualizados}")
    print(f"Transações atualizadas: {transacoes_atualizadas}")
    return {"usuarios_atualizados": usuarios_atualizados, "transacoes_atualizadas": transacoes_atualizadas}


if __name__ == "__main__":
    run_backfill()
