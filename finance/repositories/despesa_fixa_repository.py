"""
Repository para despesas fixas / recorrentes.

Localização: finance/repositories/despesa_fixa_repository.py

Collection MongoDB: despesas_fixas

Schema:
{
    "_id": ObjectId,
    "user_id": ObjectId,
    "nome": str,
    "valor": float,
    "dia_vencimento": int,  # 1 a 31
    "ativo": bool,
    "ultimo_envio": datetime | omitido,  # instante do último lembrete (Celery)
    "ultimo_envio_mes": str | omitido,  # "YYYY-MM" — no máximo 1 lembrete/mês por despesa
}
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Mapping
from datetime import datetime

from bson import ObjectId

from core.repositories.base_repository import BaseRepository
from core.services.user_scope import get_user_scope_filter


class DespesaFixaRepository(BaseRepository):
    """Acesso à collection ``despesas_fixas`` (despesas recorrentes por usuário)."""

    COLLECTION_NAME = "despesas_fixas"

    def __init__(self):
        super().__init__(self.COLLECTION_NAME)

    def _ensure_indexes(self) -> None:
        self.collection.create_index("user_id")
        self.collection.create_index([("user_id", 1), ("ativo", 1)])
        self.collection.create_index([("user_id", 1), ("dia_vencimento", 1)])

    @staticmethod
    def _normalize_user_id(user_id: str | ObjectId) -> ObjectId:
        if isinstance(user_id, ObjectId):
            return user_id
        return ObjectId(str(user_id))

    def find_by_user(
        self,
        user_id: str,
        *,
        apenas_ativas: bool = True,
        limit: int = 200,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """Lista despesas fixas do usuário (por padrão só ``ativo: true``)."""
        if not user_id:
            raise ValueError("user_id é obrigatório")
        query: Dict[str, Any] = {"user_id": self._normalize_user_id(user_id)}
        if apenas_ativas:
            query["ativo"] = True
        return self.find_many(query=query, limit=limit, skip=skip, sort=("dia_vencimento", 1))

    def find_for_read_scope(
        self,
        user: Mapping[str, Any],
        *,
        apenas_ativas: bool = True,
        limit: int = 200,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """Lista despesas fixas no escopo de leitura (família ou individual)."""
        query: Dict[str, Any] = dict(get_user_scope_filter(user))
        if apenas_ativas:
            query["ativo"] = True
        return self.find_many(query=query, limit=limit, skip=skip, sort=("dia_vencimento", 1))

    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[override]
        """
        Cria documento com validação mínima de schema.

        Campos esperados: user_id, nome, valor, dia_vencimento;
        opcionais: ativo (default True), ultimo_envio (datetime).
        """
        doc = dict(data)
        doc["user_id"] = self._normalize_user_id(doc["user_id"])
        nome = (doc.get("nome") or "").strip()
        if not nome:
            raise ValueError("nome é obrigatório")
        doc["nome"] = nome
        doc["valor"] = float(doc["valor"])
        dia = int(doc["dia_vencimento"])
        if dia < 1 or dia > 31:
            raise ValueError("dia_vencimento deve estar entre 1 e 31")
        doc["dia_vencimento"] = dia
        doc["ativo"] = bool(doc.get("ativo", True))
        if "ultimo_envio" in doc and doc["ultimo_envio"] is None:
            del doc["ultimo_envio"]
        elif "ultimo_envio" in doc and not isinstance(doc["ultimo_envio"], datetime):
            raise ValueError("ultimo_envio deve ser datetime ou omitido")
        return super().create(doc)

    def set_ativo(self, document_id: str, user_id: str, ativo: bool) -> bool:
        """Atualiza flag ativo garantindo que o documento pertence ao usuário."""
        try:
            oid = ObjectId(document_id)
            uid = self._normalize_user_id(user_id)
            result = self.collection.update_one(
                {"_id": oid, "user_id": uid},
                {"$set": {"ativo": bool(ativo)}},
            )
            return result.modified_count > 0
        except Exception:
            return False

    def update_ultimo_envio(
        self, document_id: str, user_id: str, quando: Optional[datetime] = None
    ) -> bool:
        """Define ``ultimo_envio`` (default: agora UTC)."""
        try:
            oid = ObjectId(document_id)
            uid = self._normalize_user_id(user_id)
            ts = quando if quando is not None else datetime.utcnow()
            result = self.collection.update_one(
                {"_id": oid, "user_id": uid},
                {"$set": {"ultimo_envio": ts}},
            )
            return result.modified_count > 0
        except Exception:
            return False

    def update_by_user(
        self,
        document_id: str,
        user_id: str,
        *,
        nome: str,
        valor: float,
        dia_vencimento: int,
    ) -> bool:
        """Atualiza nome, valor e dia_vencimento; retorna False se o documento não for do usuário."""
        try:
            oid = ObjectId(document_id)
        except Exception as exc:
            raise ValueError("ID inválido") from exc
        uid = self._normalize_user_id(user_id)
        nome_clean = (nome or "").strip()
        if not nome_clean:
            raise ValueError("nome é obrigatório")
        dia = int(dia_vencimento)
        if dia < 1 or dia > 31:
            raise ValueError("dia_vencimento deve estar entre 1 e 31")
        result = self.collection.update_one(
            {"_id": oid, "user_id": uid},
            {
                "$set": {
                    "nome": nome_clean,
                    "valor": float(valor),
                    "dia_vencimento": dia,
                }
            },
        )
        return result.matched_count > 0

    def delete_by_user(self, document_id: str, user_id: str) -> bool:
        """Remove o documento se pertencer ao usuário."""
        try:
            oid = ObjectId(document_id)
            uid = self._normalize_user_id(user_id)
            result = self.collection.delete_one({"_id": oid, "user_id": uid})
            return result.deleted_count > 0
        except Exception:
            return False
