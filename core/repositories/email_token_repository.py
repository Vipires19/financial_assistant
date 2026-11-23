"""
Repository para a collection email_tokens no MongoDB.

Tokens de verificação de email e recuperação de senha.
Estrutura: user_id, email, token, tipo, expira_em, usado, created_at.
"""
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from core.database import get_database


def _utcnow():
    """Datetime UTC para comparação e armazenamento."""
    return datetime.now(timezone.utc)


class EmailTokenRepository:
    """Operações sobre a collection email_tokens."""

    def __init__(self):
        self.db = get_database()
        self.collection = self.db["email_tokens"]
        self._ensure_indexes()

    def _ensure_indexes(self):
        """Índices para token (único) e expira_em (limpeza)."""
        self.collection.create_index("token", unique=True)
        self.collection.create_index("expira_em")

    def create(self, user_id: str, email: str, token: str, tipo: str) -> Dict[str, Any]:
        """
        Cria registro de token.
        tipo: "verificacao" ou "recuperacao"
        expira_em: now + 10 minutos em UTC.
        """
        from datetime import timedelta
        now = _utcnow()
        expira_em = now + timedelta(minutes=10)
        doc = {
            "user_id": user_id,
            "email": email,
            "token": token,
            "tipo": tipo,
            "expira_em": expira_em,
            "usado": False,
            "created_at": now,
        }
        result = self.collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    def find_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Busca token por valor. Retorna None se não existir."""
        return self.collection.find_one({"token": token})

    def is_valid(self, token: str, tipo: Optional[str] = None) -> bool:
        """
        Verifica se o token existe, não foi usado e não expirou.
        Se tipo for passado, também verifica o tipo.
        """
        doc = self.find_by_token(token)
        if not doc:
            return False
        if doc.get("usado"):
            return False
        expira_em = doc.get("expira_em")
        if not expira_em:
            return False
        now = _utcnow()
        if hasattr(expira_em, "tzinfo") and expira_em.tzinfo is None:
            from datetime import timezone as tz
            expira_em = expira_em.replace(tzinfo=tz.utc)
        if expira_em < now:
            return False
        if tipo is not None and doc.get("tipo") != tipo:
            return False
        return True

    def mark_used(self, token: str) -> bool:
        """Marca token como usado. Retorna True se atualizou."""
        result = self.collection.update_one(
            {"token": token},
            {"$set": {"usado": True, "updated_at": _utcnow()}},
        )
        return result.modified_count > 0
