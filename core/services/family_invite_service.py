"""
Convites para membros do modo família.

Localização: core/services/family_invite_service.py
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from bson import ObjectId

from core.database import get_client, get_family_groups_collection, get_family_invites_collection
from core.models.user_model import UserModel
from core.repositories.user_repository import UserRepository
from core.services.plan_service import (
    ERR_ACESSO_FAMILIA_EXPIRADO,
    ERR_CONVIDAR_PLANO,
    PLAN_FAMILIA,
    get_limite_membros,
    get_plano_recursos,
    usuario_tem_acesso_familia,
)
from services.waha_sender import enviar_mensagem_waha

logger = logging.getLogger(__name__)

_FAMILY_INVITES_COMPOUND_INDEX_OK = False


def _ensure_family_invites_indexes(coll) -> None:
    """Índice composto para consultas por família + telefone + status (idempotente por processo)."""
    global _FAMILY_INVITES_COMPOUND_INDEX_OK
    if _FAMILY_INVITES_COMPOUND_INDEX_OK:
        return
    try:
        coll.create_index(
            [("family_group_id", 1), ("telefone", 1), ("status", 1)]
        )
        _FAMILY_INVITES_COMPOUND_INDEX_OK = True
    except Exception as e:
        logger.warning(
            "[family_invite] Não foi possível criar índice em family_invites: %s",
            e,
        )


def _same_member_user_id(stored: Any, candidate: ObjectId) -> bool:
    """Compara user_id em documento de membro (ObjectId ou string) com ``candidate``."""
    if stored is None:
        return False
    try:
        sid = stored if isinstance(stored, ObjectId) else ObjectId(str(stored))
        return sid == candidate
    except Exception:
        return False


def _expirado(exp: Any) -> bool:
    """Compara ``expira_em`` (UTC armazenado no Mongo) com o instante atual em UTC."""
    if exp is None:
        return True
    if getattr(exp, "tzinfo", None):
        exp_naive = exp.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        exp_naive = exp
    return exp_naive < datetime.utcnow()


def _nome_convidante(user: Dict[str, Any]) -> str:
    nome = (user.get("nome") or "").strip()
    if nome:
        return nome
    email = (user.get("email") or "").strip()
    if email and "@" in email:
        return email.split("@", 1)[0]
    return "Alguém"


def create_family_invite(
    user_id: ObjectId,
    nome: str,
    telefone: str,
    *,
    signup_base_url: str,
) -> Dict[str, Any]:
    """
    Cria convite pendente, persiste no Mongo e tenta enviar WhatsApp.

    ``signup_base_url`` deve ser a origem pública (ex.: ``https://app.exemplo.com``),
    sem barra final; o link de cadastro será ``{signup_base_url}/register/?token=...``.

    Raises:
        ValueError: regras de negócio (owner, família, limite, dados inválidos).
    """
    nome_limpo = str(nome or "").strip()
    tel_limpo = str(telefone or "").strip()
    if not nome_limpo:
        raise ValueError("Nome do convidado é obrigatório")
    if not tel_limpo:
        raise ValueError("Telefone é obrigatório")

    user_repo = UserRepository()
    user = user_repo.find_by_id(str(user_id))
    if not user:
        raise ValueError("Usuário não encontrado")

    if get_plano_recursos(user) != PLAN_FAMILIA:
        raise ValueError(ERR_CONVIDAR_PLANO)

    if not usuario_tem_acesso_familia(user):
        raise ValueError(ERR_ACESSO_FAMILIA_EXPIRADO)

    if not user.get("family_group_id"):
        raise ValueError("Usuário não possui família")

    if user.get("role_in_family") != UserModel.ROLE_IN_FAMILY_OWNER:
        raise ValueError("Apenas o dono da família pode convidar membros")

    fg_id = user["family_group_id"]
    if isinstance(fg_id, str):
        try:
            fg_id = ObjectId(fg_id)
        except Exception:
            raise ValueError("Família não encontrada") from None

    coll_fg = get_family_groups_collection(get_client())
    family = coll_fg.find_one({"_id": fg_id})
    if not family:
        raise ValueError("Família não encontrada")

    members = family.get("members") or []
    limite_raw = family.get("limite_membros")
    limite_doc = int(limite_raw) if limite_raw is not None else get_limite_membros(user)
    limite = min(limite_doc, get_limite_membros(user))
    if len(members) >= limite:
        raise ValueError("Limite de membros atingido")

    coll_inv = get_family_invites_collection(get_client())
    _ensure_family_invites_indexes(coll_inv)

    now = datetime.utcnow()
    existing_invite = coll_inv.find_one(
        {
            "family_group_id": family["_id"],
            "telefone": tel_limpo,
            "status": "pendente",
            "expira_em": {"$gt": now},
        }
    )
    if existing_invite:
        raise ValueError("Já existe um convite pendente para este telefone")

    token = str(uuid.uuid4())
    invite_doc: Dict[str, Any] = {
        "family_group_id": family["_id"],
        "telefone": tel_limpo,
        "nome": nome_limpo,
        "token": token,
        "status": "pendente",
        "expira_em": now + timedelta(days=2),
        "created_at": now,
    }

    coll_inv.insert_one(invite_doc)

    base = (signup_base_url or "").strip().rstrip("/")
    link = f"{base}/register/?token={token}"
    convidante = _nome_convidante(user)
    texto = (
        f"{convidante} te convidou para o plano família do Leozera 💸\n\n"
        f"Crie sua conta aqui:\n"
        f"{link}"
    )

    try:
        ok = enviar_mensagem_waha(tel_limpo, texto)
        if not ok:
            logger.error(
                "[family_invite] Falha ao enviar WhatsApp (invite salvo). token=%s telefone=%s",
                token,
                tel_limpo,
            )
    except Exception as e:
        logger.exception(
            "[family_invite] Erro ao enviar WhatsApp (invite salvo): %s", e
        )

    return {
        "token": token,
        "nome": nome_limpo,
        "telefone": tel_limpo,
        "expira_em": invite_doc["expira_em"].isoformat() + "Z",
    }


def accept_family_invite(user_id: ObjectId, token: str) -> Dict[str, Any]:
    """
    Vincula o usuário à família do convite, atualiza membros e marca o convite como aceito.

    Ordem: validações → atualizar família → usuário → convite.
    """
    token_limpo = str(token or "").strip()
    if not token_limpo:
        raise ValueError("Convite inválido")

    client = get_client()
    coll_inv = get_family_invites_collection(client)
    invite = coll_inv.find_one({"token": token_limpo})
    if not invite:
        raise ValueError("Convite inválido")

    if invite.get("status") != "pendente":
        raise ValueError("Convite já utilizado")

    if _expirado(invite.get("expira_em")):
        raise ValueError("Convite expirado")

    user_repo = UserRepository()
    user = user_repo.find_by_id(str(user_id))
    if not user:
        raise ValueError("Usuário não encontrado")

    if user.get("family_group_id"):
        raise ValueError("Usuário já pertence a uma família")

    fg_id = invite.get("family_group_id")
    if isinstance(fg_id, str):
        try:
            fg_id = ObjectId(fg_id)
        except Exception:
            raise ValueError("Convite inválido") from None

    coll_fg = get_family_groups_collection(client)
    family = coll_fg.find_one({"_id": fg_id})
    if not family:
        raise ValueError("Família não encontrada")

    members = family.get("members") or []
    limite_raw = family.get("limite_membros")
    limite_doc = int(limite_raw) if limite_raw is not None else 5
    owner_oid = family.get("owner_id")
    owner = None
    if owner_oid is not None:
        owner = user_repo.find_by_id(str(owner_oid))
    limite_owner = get_limite_membros(owner) if owner else limite_doc
    limite = min(limite_doc, limite_owner)
    if len(members) >= limite:
        raise ValueError("Família atingiu o limite de membros do plano")

    already_member = any(
        _same_member_user_id(m.get("user_id"), user_id) for m in members
    )
    if already_member:
        raise ValueError("Usuário já é membro desta família")

    now = datetime.utcnow()
    invite_oid = invite["_id"]
    member_doc = {
        "user_id": user_id,
        "role": UserModel.ROLE_IN_FAMILY_MEMBER,
        "joined_at": now,
    }
    member_pushed = False
    user_updated = False

    try:
        coll_fg.update_one(
            {"_id": family["_id"]},
            {"$push": {"members": member_doc}},
        )
        member_pushed = True

        user_repo.collection.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "family_group_id": family["_id"],
                    "role_in_family": UserModel.ROLE_IN_FAMILY_MEMBER,
                    "updated_at": now,
                }
            },
        )
        user_updated = True

        coll_inv.update_one(
            {"_id": invite_oid},
            {
                "$set": {
                    "status": "aceito",
                    "accepted_at": now,
                }
            },
        )
    except Exception:
        logger.exception(
            "Erro ao aceitar convite, iniciando rollback (user_id=%s token=%s)",
            user_id,
            token_limpo,
        )
        if user_updated:
            try:
                user_repo.collection.update_one(
                    {"_id": user_id},
                    {
                        "$unset": {
                            "family_group_id": "",
                            "role_in_family": "",
                        },
                        "$set": {"updated_at": datetime.utcnow()},
                    },
                )
            except Exception:
                logger.exception(
                    "Falha no rollback dos campos de família do usuário (user_id=%s)",
                    user_id,
                )
        if member_pushed:
            try:
                coll_fg.update_one(
                    {"_id": family["_id"]},
                    {"$pull": {"members": {"user_id": user_id}}},
                )
            except Exception:
                logger.exception(
                    "Falha no rollback do membro da família (family_id=%s)",
                    family["_id"],
                )
        raise

    return {
        "family_group_id": str(family["_id"]),
        "nome": family.get("nome", ""),
    }
