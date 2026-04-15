"""
UI e payloads para modo família (nomes, contexto do dashboard, página da família).

Localização: core/services/family_ui_service.py
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from bson import ObjectId

from core.database import get_client, get_family_groups_collection
from core.models.user_model import UserModel
from core.repositories.user_repository import UserRepository
from core.services.plan_service import (
    get_plano_recursos,
    is_family_read_only,
    usuario_tem_acesso_familia,
)
from core.services.user_scope import resolve_user_read_scope


def user_display_name(doc: Optional[Dict[str, Any]]) -> str:
    if not doc:
        return "Membro"
    nome = (doc.get("nome") or "").strip()
    if nome:
        return nome
    email = (doc.get("email") or "").strip()
    if email and "@" in email:
        return email.split("@", 1)[0].title()
    return "Membro"


def format_phone_br(raw: Any) -> str:
    if raw is None:
        return "—"
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) >= 11:
        return f"+{digits[0:2]} {digits[2:4]} {digits[4:9]}-{digits[9:11]}"
    if len(digits) >= 10:
        return f"+{digits[0:2]} {digits[2:6]}-{digits[6:10]}"
    if digits:
        return digits
    return "—"


def _join_names_summary(names: List[str]) -> str:
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} + {names[1]}"
    return " + ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "")


def build_family_context(user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Contexto leve para o dashboard (banner Modo Família).
    """
    uid = user.get("_id")
    self_str = str(uid) if uid is not None else ""
    if not user.get("family_group_id"):
        return {
            "active": False,
            "member_count": 1,
            "names_summary": "",
            "first_names": [],
            "can_invite": False,
            "is_owner": False,
            "family_read_only": False,
        }

    _scope, member_ids = resolve_user_read_scope(user)
    repo = UserRepository()
    names: List[str] = []
    for mid in member_ids:
        u = repo.find_by_id(str(mid))
        names.append(user_display_name(u))

    role = (user.get("role_in_family") or "").strip().lower()
    is_owner = role == UserModel.ROLE_IN_FAMILY_OWNER
    read_only = is_family_read_only(user)
    pode_familia = usuario_tem_acesso_familia(user)

    return {
        "active": True,
        "member_count": len(member_ids),
        "names_summary": _join_names_summary(names),
        "first_names": names[:5],
        "can_invite": is_owner and pode_familia,
        "is_owner": is_owner,
        "family_read_only": read_only,
    }


def member_id_to_display_names(member_ids: List[ObjectId]) -> Dict[str, str]:
    """Mapa user_id (str) -> nome para exibição."""
    repo = UserRepository()
    out: Dict[str, str] = {}
    for mid in member_ids:
        u = repo.find_by_id(str(mid))
        out[str(mid)] = user_display_name(u)
    return out


def get_family_hub_context(viewer: Dict[str, Any]) -> Dict[str, Any]:
    """
    Contexto para GET /family/ (hub: vazio ou detalhe).
    """
    uid = viewer.get("_id")
    if not uid:
        return {"has_family": False}

    if not viewer.get("family_group_id"):
        return {
            "has_family": False,
            "viewer": viewer,
            "plano_recursos": get_plano_recursos(viewer),
            "family_read_only": False,
        }

    coll = get_family_groups_collection(get_client())
    fg_id = viewer["family_group_id"]
    fg_oid = fg_id if isinstance(fg_id, ObjectId) else ObjectId(str(fg_id))
    family = coll.find_one({"_id": fg_oid})
    if not family:
        return {
            "has_family": False,
            "viewer": viewer,
            "plano_recursos": get_plano_recursos(viewer),
            "family_read_only": False,
        }

    repo = UserRepository()
    self_str = str(uid)
    members_out: List[Dict[str, Any]] = []

    for m in family.get("members") or []:
        muid = m.get("user_id")
        if muid is None:
            continue
        oid = muid if isinstance(muid, ObjectId) else ObjectId(str(muid))
        u = repo.find_by_id(str(oid))
        role_m = (m.get("role") or "").strip().lower()
        is_owner_member = role_m == UserModel.ROLE_IN_FAMILY_OWNER
        members_out.append(
            {
                "user_id": str(oid),
                "nome": user_display_name(u),
                "telefone_fmt": format_phone_br(
                    (u or {}).get("telefone") or (u or {}).get("phone")
                ),
                "is_you": str(oid) == self_str,
                "badge_owner": is_owner_member,
                "badge_member": not is_owner_member,
            }
        )

    role_v = (viewer.get("role_in_family") or "").strip().lower()
    is_owner_hub = role_v == UserModel.ROLE_IN_FAMILY_OWNER
    read_only = is_family_read_only(viewer)
    pode_familia = usuario_tem_acesso_familia(viewer)
    can_invite = is_owner_hub and pode_familia

    return {
        "has_family": True,
        "viewer": viewer,
        "plano_recursos": get_plano_recursos(viewer),
        "family_read_only": read_only,
        "family_name": (family.get("nome") or "Família").strip(),
        "member_count": len(members_out),
        "members": members_out,
        "can_invite": can_invite,
    }


def build_family_api_detail(viewer: Dict[str, Any]) -> Dict[str, Any]:
    """Payload JSON para GET /api/family/."""
    ctx = get_family_hub_context(viewer)
    if not ctx.get("has_family"):
        return {"has_family": False}
    return {
        "has_family": True,
        "family_name": ctx["family_name"],
        "member_count": ctx["member_count"],
        "members": ctx["members"],
        "can_invite": ctx["can_invite"],
        "plano_recursos": ctx.get("plano_recursos"),
        "family_read_only": ctx.get("family_read_only", False),
    }