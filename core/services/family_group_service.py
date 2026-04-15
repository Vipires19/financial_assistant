"""
Serviço de grupos familiares (modo família).

Localização: core/services/family_group_service.py
"""
import logging
from datetime import datetime
from typing import Dict, Any

from bson import ObjectId

from core.database import get_client, get_family_groups_collection
from core.models.user_model import UserModel
from core.repositories.user_repository import UserRepository
from core.services.plan_service import (
    ERR_ACESSO_FAMILIA_EXPIRADO,
    ERR_CRIAR_FAMILIA_PLANO,
    PLAN_FAMILIA,
    get_limite_membros,
    get_plano_recursos,
    usuario_tem_acesso_familia,
)

logger = logging.getLogger(__name__)


def create_family_group(user_id: ObjectId, nome: str) -> Dict[str, Any]:
    """
    Cria um documento em ``family_groups`` e associa o usuário como owner.

    Raises:
        ValueError: nome vazio, usuário inexistente ou já pertencente a uma família.
    """
    nome_limpo = str(nome or "").strip()
    if not nome_limpo:
        raise ValueError("Nome da família é obrigatório")

    user_repo = UserRepository()
    user = user_repo.find_by_id(str(user_id))
    if not user:
        raise ValueError("Usuário não encontrado")

    if get_plano_recursos(user) != PLAN_FAMILIA:
        raise ValueError(ERR_CRIAR_FAMILIA_PLANO)

    if not usuario_tem_acesso_familia(user):
        raise ValueError(ERR_ACESSO_FAMILIA_EXPIRADO)

    if user.get("family_group_id"):
        raise ValueError("Usuário já pertence a uma família")

    limite = get_limite_membros(user)
    now = datetime.utcnow()
    family_doc = {
        "nome": nome_limpo,
        "owner_id": user_id,
        "members": [
            {
                "user_id": user_id,
                "role": UserModel.ROLE_IN_FAMILY_OWNER,
                "joined_at": now,
            }
        ],
        "limite_membros": limite,
        "created_at": now,
    }

    coll = get_family_groups_collection(get_client())
    result = coll.insert_one(family_doc)
    family_id = result.inserted_id

    try:
        user_repo.collection.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "family_group_id": family_id,
                    "role_in_family": UserModel.ROLE_IN_FAMILY_OWNER,
                    "updated_at": now,
                }
            },
        )
    except Exception as e:
        coll.delete_one({"_id": family_id})
        logger.error(
            "Erro ao atualizar usuário após criar família, rollback executado: %s", e
        )
        raise

    return {
        "family_group_id": str(family_id),
        "nome": nome_limpo,
    }
