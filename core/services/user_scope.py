"""
Escopo de leitura para modo família: agrega dados de todos os membros.

Leitura: família (quando houver ``family_group_id`` e documento em ``family_groups``).
Escrita: permanece por usuário (não usar este módulo em CRUD).

Localização: core/services/user_scope.py
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from bson import ObjectId

from core.database import get_client, get_family_groups_collection


def _normalize_oid(value: Any) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    return ObjectId(str(value))


def resolve_user_read_scope(user: Dict[str, Any]) -> Tuple[Dict[str, Any], List[ObjectId]]:
    """
    Resolve filtro MongoDB para ``user_id`` e a lista de membros (ObjectIds).

    - Sem família ou família não encontrada ou sem membros: apenas o próprio usuário.
    - Com família: ``{"user_id": {"$in": [...]}}``; o próprio usuário é garantido na lista.
    """
    if not user or not user.get("_id"):
        raise ValueError("user com _id é obrigatório")

    self_id = _normalize_oid(user["_id"])
    fg_id = user.get("family_group_id")

    if not fg_id:
        return ({"user_id": self_id}, [self_id])

    coll = get_family_groups_collection(get_client())
    fg_oid = _normalize_oid(fg_id)
    family = coll.find_one({"_id": fg_oid})

    if not family:
        return ({"user_id": self_id}, [self_id])

    member_ids: List[ObjectId] = []
    for m in family.get("members") or []:
        muid = m.get("user_id")
        if muid is None:
            continue
        member_ids.append(_normalize_oid(muid))

    if not member_ids:
        return ({"user_id": self_id}, [self_id])

    if self_id not in member_ids:
        member_ids.append(self_id)

    return ({"user_id": {"$in": member_ids}}, member_ids)


def get_user_scope_filter(user: Dict[str, Any]) -> Dict[str, Any]:
    """Filtro MongoDB para queries de leitura (ex.: ``{**get_user_scope_filter(u), ...}``)."""
    return resolve_user_read_scope(user)[0]


def get_family_member_ids(user: Dict[str, Any]) -> List[ObjectId]:
    """IDs dos usuários no escopo de leitura atual (individual ou família)."""
    return resolve_user_read_scope(user)[1]
