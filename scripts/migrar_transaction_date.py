"""
Migração: adiciona o campo transaction_date nas transações que ainda não possuem.
Para cada documento onde transaction_date não existe, define transaction_date = created_at.

Uso (na raiz do projeto financeiro):
    python scripts/migrar_transaction_date.py

Ou com Django:
    python manage.py shell
    >>> from scripts.migrar_transaction_date import run_migration
    >>> run_migration()
"""
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Permite rodar como script standalone a partir da raiz do projeto financeiro
if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
    django.setup()

from core.database import get_database


def run_migration():
    """
    Atualiza todas as transações sem transaction_date, definindo transaction_date = created_at.
    Não altera registros que já possuem transaction_date.
    """
    db = get_database()
    coll = db.transactions

    query = {"transaction_date": {"$exists": False}}
    encontradas = coll.count_documents(query)

    if encontradas == 0:
        logger.info("Transações sem transaction_date encontradas: 0")
        logger.info("Transações atualizadas com sucesso: 0")
        return {"encontradas": 0, "atualizadas": 0}

    # update_many com pipeline de agregação: define transaction_date = created_at
    result = coll.update_many(
        query,
        [{"$set": {"transaction_date": "$created_at"}}],
    )

    atualizadas = result.modified_count

    logger.info(f"Transações sem transaction_date encontradas: {encontradas}")
    logger.info(f"Transações atualizadas com sucesso: {atualizadas}")

    return {"encontradas": encontradas, "atualizadas": atualizadas}


if __name__ == "__main__":
    run_migration()
