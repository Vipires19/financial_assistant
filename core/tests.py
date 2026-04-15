# Tests para o core
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from bson import ObjectId
from django.test import SimpleTestCase

from core.models.user_model import UserModel
from core.services.family_group_service import create_family_group
from core.services.family_invite_service import (
    accept_family_invite,
    create_family_invite,
)
from core.services.plan_service import (
    ERR_ACESSO_FAMILIA_EXPIRADO,
    ERR_CONVIDAR_PLANO,
    ERR_CRIAR_FAMILIA_PLANO,
    ERR_DOWNGRADE_INDIVIDUAL_COM_FAMILIA,
    PLAN_FAMILIA,
    PLAN_INDIVIDUAL,
    get_limite_membros,
    get_plano_recursos,
    is_family_read_only,
    usuario_tem_acesso_familia,
    validate_tipo_plano_individual,
)
import core.services.user_scope as user_scope_mod


class PlanServiceTests(SimpleTestCase):
    """Plano de recursos (fonte única) e limites."""

    def test_get_limite_membros(self):
        self.assertEqual(get_limite_membros(None), 1)
        self.assertEqual(get_limite_membros({"tipo_plano": PLAN_INDIVIDUAL}), 1)
        self.assertEqual(get_limite_membros({"tipo_plano": PLAN_FAMILIA}), 5)

    def test_get_plano_recursos_prioridade_tipo_plano_sobre_billing(self):
        u = {
            "tipo_plano": PLAN_INDIVIDUAL,
            "assinatura": {"plano": "familia_mensal"},
        }
        self.assertEqual(get_plano_recursos(u), PLAN_INDIVIDUAL)

    def test_get_plano_recursos_billing_familia(self):
        u = {"assinatura": {"plano": "familia_anual"}}
        self.assertEqual(get_plano_recursos(u), PLAN_FAMILIA)

    def test_is_family_read_only(self):
        fg = ObjectId()
        self.assertFalse(is_family_read_only({"tipo_plano": PLAN_FAMILIA, "family_group_id": fg}))
        self.assertTrue(is_family_read_only({"tipo_plano": PLAN_INDIVIDUAL, "family_group_id": fg}))

    def test_validate_downgrade_individual_com_familia(self):
        with self.assertRaisesMessage(ValueError, ERR_DOWNGRADE_INDIVIDUAL_COM_FAMILIA):
            validate_tipo_plano_individual({"family_group_id": ObjectId()})

    def test_usuario_tem_acesso_familia_grace(self):
        futuro = datetime.now(timezone.utc) + timedelta(days=5)
        u = {
            "tipo_plano": PLAN_FAMILIA,
            "cancelamento_agendado": True,
            "data_fim_acesso": futuro,
        }
        self.assertTrue(usuario_tem_acesso_familia(u))

    def test_usuario_tem_acesso_familia_grace_expirado(self):
        passado = datetime.now(timezone.utc) - timedelta(days=1)
        u = {
            "tipo_plano": PLAN_FAMILIA,
            "cancelamento_agendado": True,
            "data_fim_acesso": passado,
        }
        self.assertFalse(usuario_tem_acesso_familia(u))


class FamilyGroupServiceTests(SimpleTestCase):
    """Testes unitários de create_family_group (Mongo mockado)."""

    @patch("core.services.family_group_service.get_family_groups_collection")
    @patch("core.services.family_group_service.get_client")
    @patch("core.services.family_group_service.UserRepository")
    def test_cria_familia_quando_usuario_sem_familia(
        self, mock_user_repo_cls, _mock_client, mock_get_coll
    ):
        uid = ObjectId()
        family_oid = ObjectId()
        mock_repo = mock_user_repo_cls.return_value
        mock_repo.find_by_id.return_value = {
            "_id": uid,
            "email": "a@b.com",
            "tipo_plano": UserModel.PLAN_FAMILIA,
        }
        mock_repo.collection = MagicMock()
        mock_fg = MagicMock()
        mock_fg.insert_one.return_value = MagicMock(inserted_id=family_oid)
        mock_get_coll.return_value = mock_fg

        out = create_family_group(uid, "Família Teste")

        self.assertEqual(out["nome"], "Família Teste")
        self.assertEqual(out["family_group_id"], str(family_oid))
        mock_fg.insert_one.assert_called_once()
        doc = mock_fg.insert_one.call_args[0][0]
        self.assertEqual(doc["nome"], "Família Teste")
        self.assertEqual(doc["owner_id"], uid)
        self.assertEqual(len(doc["members"]), 1)
        self.assertEqual(doc["members"][0]["role"], "owner")
        self.assertEqual(doc["members"][0]["user_id"], uid)
        self.assertEqual(doc["limite_membros"], 5)
        mock_repo.collection.update_one.assert_called_once()

    @patch("core.services.family_group_service.UserRepository")
    def test_individual_nao_cria_familia(self, mock_user_repo_cls):
        uid = ObjectId()
        mock_repo = mock_user_repo_cls.return_value
        mock_repo.find_by_id.return_value = {
            "_id": uid,
            "email": "a@b.com",
            "tipo_plano": UserModel.PLAN_INDIVIDUAL,
        }
        with self.assertRaisesMessage(ValueError, ERR_CRIAR_FAMILIA_PLANO):
            create_family_group(uid, "Nome")

    @patch("core.services.family_group_service.UserRepository")
    def test_erro_quando_ja_em_familia(self, mock_user_repo_cls):
        uid = ObjectId()
        mock_repo = mock_user_repo_cls.return_value
        mock_repo.find_by_id.return_value = {
            "_id": uid,
            "family_group_id": ObjectId(),
            "tipo_plano": UserModel.PLAN_FAMILIA,
        }
        with self.assertRaisesMessage(
            ValueError, "Usuário já pertence a uma família"
        ):
            create_family_group(uid, "Nome")

    @patch("core.services.family_group_service.UserRepository")
    def test_sem_acesso_apos_grace_expirado(self, mock_user_repo_cls):
        uid = ObjectId()
        mock_repo = mock_user_repo_cls.return_value
        mock_repo.find_by_id.return_value = {
            "_id": uid,
            "email": "a@b.com",
            "tipo_plano": UserModel.PLAN_FAMILIA,
            "cancelamento_agendado": True,
            "data_fim_acesso": datetime.now(timezone.utc) - timedelta(days=1),
        }
        with self.assertRaisesMessage(ValueError, ERR_ACESSO_FAMILIA_EXPIRADO):
            create_family_group(uid, "Nome")

    @patch("core.services.family_group_service.get_family_groups_collection")
    @patch("core.services.family_group_service.get_client")
    @patch("core.services.family_group_service.UserRepository")
    def test_rollback_se_update_usuario_falhar(
        self, mock_user_repo_cls, _mock_client, mock_get_coll
    ):
        uid = ObjectId()
        family_oid = ObjectId()
        mock_repo = mock_user_repo_cls.return_value
        mock_repo.find_by_id.return_value = {
            "_id": uid,
            "email": "a@b.com",
            "tipo_plano": UserModel.PLAN_FAMILIA,
        }
        mock_repo.collection = MagicMock()
        mock_repo.collection.update_one.side_effect = RuntimeError("erro de escrita")
        mock_fg = MagicMock()
        mock_fg.insert_one.return_value = MagicMock(inserted_id=family_oid)
        mock_get_coll.return_value = mock_fg

        with self.assertRaises(RuntimeError):
            create_family_group(uid, "Família X")

        mock_fg.delete_one.assert_called_once_with({"_id": family_oid})


class FamilyInviteServiceTests(SimpleTestCase):
    """Testes de create_family_invite (Mongo e WAHA mockados)."""

    @patch("core.services.family_invite_service.enviar_mensagem_waha")
    @patch("core.services.family_invite_service.get_family_invites_collection")
    @patch("core.services.family_invite_service.get_family_groups_collection")
    @patch("core.services.family_invite_service.get_client")
    @patch("core.services.family_invite_service.UserRepository")
    def test_owner_convite_sucesso(
        self,
        mock_ur,
        _gc,
        mock_fg_coll,
        mock_inv_coll,
        mock_waha,
    ):
        uid = ObjectId()
        fg_oid = ObjectId()
        mock_repo = mock_ur.return_value
        mock_repo.find_by_id.return_value = {
            "_id": uid,
            "email": "x@y.com",
            "nome": "João",
            "family_group_id": fg_oid,
            "role_in_family": "owner",
            "tipo_plano": UserModel.PLAN_FAMILIA,
        }
        mock_fgc = MagicMock()
        mock_fg_coll.return_value = mock_fgc
        mock_fgc.find_one.return_value = {
            "_id": fg_oid,
            "members": [{"user_id": uid}],
            "limite_membros": 5,
        }
        mock_inv = MagicMock()
        mock_inv.find_one.return_value = None
        mock_inv_coll.return_value = mock_inv

        out = create_family_invite(
            uid,
            "Lorena",
            "16999999999",
            signup_base_url="https://app.exemplo.com",
        )

        self.assertIn("token", out)
        self.assertEqual(out["nome"], "Lorena")
        mock_inv.insert_one.assert_called_once()
        doc = mock_inv.insert_one.call_args[0][0]
        self.assertEqual(doc["status"], "pendente")
        self.assertEqual(doc["nome"], "Lorena")
        mock_waha.assert_called_once()

    @patch("core.services.family_invite_service.UserRepository")
    def test_membro_nao_pode_convidar(self, mock_ur):
        uid = ObjectId()
        mock_ur.return_value.find_by_id.return_value = {
            "_id": uid,
            "family_group_id": ObjectId(),
            "role_in_family": "member",
            "tipo_plano": UserModel.PLAN_FAMILIA,
        }
        with self.assertRaisesMessage(
            ValueError, "Apenas o dono da família pode convidar membros"
        ):
            create_family_invite(
                uid, "A", "16999999999", signup_base_url="https://x.com"
            )

    @patch("core.services.family_invite_service.UserRepository")
    def test_sem_familia(self, mock_ur):
        uid = ObjectId()
        mock_ur.return_value.find_by_id.return_value = {
            "_id": uid,
            "role_in_family": None,
            "tipo_plano": UserModel.PLAN_FAMILIA,
        }
        with self.assertRaisesMessage(ValueError, "Usuário não possui família"):
            create_family_invite(
                uid, "A", "16999999999", signup_base_url="https://x.com"
            )

    @patch("core.services.family_invite_service.UserRepository")
    def test_plano_individual_nao_convidar(self, mock_ur):
        uid = ObjectId()
        fg_oid = ObjectId()
        mock_ur.return_value.find_by_id.return_value = {
            "_id": uid,
            "family_group_id": fg_oid,
            "role_in_family": "owner",
            "tipo_plano": UserModel.PLAN_INDIVIDUAL,
        }
        with self.assertRaisesMessage(ValueError, ERR_CONVIDAR_PLANO):
            create_family_invite(
                uid, "A", "16999999999", signup_base_url="https://x.com"
            )

    @patch("core.services.family_invite_service.get_family_groups_collection")
    @patch("core.services.family_invite_service.get_client")
    @patch("core.services.family_invite_service.UserRepository")
    def test_limite_membros(self, mock_ur, _gc, mock_fg_coll):
        uid = ObjectId()
        fg_oid = ObjectId()
        mock_ur.return_value.find_by_id.return_value = {
            "_id": uid,
            "family_group_id": fg_oid,
            "role_in_family": "owner",
            "tipo_plano": UserModel.PLAN_FAMILIA,
        }
        members = [{"user_id": ObjectId()} for _ in range(5)]
        mock_fgc = MagicMock()
        mock_fg_coll.return_value = mock_fgc
        mock_fgc.find_one.return_value = {
            "_id": fg_oid,
            "members": members,
            "limite_membros": 5,
        }
        with self.assertRaisesMessage(ValueError, "Limite de membros atingido"):
            create_family_invite(
                uid, "A", "16999999999", signup_base_url="https://x.com"
            )

    @patch("core.services.family_invite_service.enviar_mensagem_waha")
    @patch("core.services.family_invite_service.get_family_invites_collection")
    @patch("core.services.family_invite_service.get_family_groups_collection")
    @patch("core.services.family_invite_service.get_client")
    @patch("core.services.family_invite_service.UserRepository")
    def test_waha_falha_mas_convite_salvo(
        self,
        mock_ur,
        _gc,
        mock_fg_coll,
        mock_inv_coll,
        mock_waha,
    ):
        mock_waha.return_value = False
        uid = ObjectId()
        fg_oid = ObjectId()
        mock_ur.return_value.find_by_id.return_value = {
            "_id": uid,
            "nome": "Z",
            "family_group_id": fg_oid,
            "role_in_family": "owner",
            "tipo_plano": UserModel.PLAN_FAMILIA,
        }
        mock_fgc = MagicMock()
        mock_fg_coll.return_value = mock_fgc
        mock_fgc.find_one.return_value = {
            "_id": fg_oid,
            "members": [{"user_id": uid}],
            "limite_membros": 5,
        }
        mock_inv = MagicMock()
        mock_inv.find_one.return_value = None
        mock_inv_coll.return_value = mock_inv

        out = create_family_invite(
            uid, "B", "16988888888", signup_base_url="https://app.exemplo.com"
        )

        self.assertIn("token", out)
        mock_inv.insert_one.assert_called_once()

    @patch("core.services.family_invite_service.enviar_mensagem_waha")
    @patch("core.services.family_invite_service.get_family_invites_collection")
    @patch("core.services.family_invite_service.get_family_groups_collection")
    @patch("core.services.family_invite_service.get_client")
    @patch("core.services.family_invite_service.UserRepository")
    def test_convite_duplicado_mesmo_telefone(
        self,
        mock_ur,
        _gc,
        mock_fg_coll,
        mock_inv_coll,
        _waha,
    ):
        uid = ObjectId()
        fg_oid = ObjectId()
        mock_ur.return_value.find_by_id.return_value = {
            "_id": uid,
            "family_group_id": fg_oid,
            "role_in_family": "owner",
            "tipo_plano": UserModel.PLAN_FAMILIA,
        }
        mock_fg_coll.return_value.find_one.return_value = {
            "_id": fg_oid,
            "members": [{"user_id": uid}],
            "limite_membros": 5,
        }
        mock_inv = MagicMock()
        mock_inv.find_one.return_value = {"_id": ObjectId(), "status": "pendente"}
        mock_inv_coll.return_value = mock_inv

        with self.assertRaisesMessage(
            ValueError, "Já existe um convite pendente para este telefone"
        ):
            create_family_invite(
                uid, "X", "16999999999", signup_base_url="https://app.exemplo.com"
            )
        mock_inv.insert_one.assert_not_called()


class AcceptFamilyInviteTests(SimpleTestCase):
    """Testes de accept_family_invite."""

    @patch("core.services.family_invite_service.get_family_invites_collection")
    @patch("core.services.family_invite_service.get_family_groups_collection")
    @patch("core.services.family_invite_service.get_client")
    @patch("core.services.family_invite_service.UserRepository")
    def test_token_valido_sucesso(
        self, mock_ur_cls, _gc, mock_fg_coll, mock_inv_coll
    ):
        uid = ObjectId()
        fg_oid = ObjectId()
        inv_oid = ObjectId()
        exp = datetime.utcnow() + timedelta(days=1)
        mock_inv = MagicMock()
        mock_inv.find_one.return_value = {
            "_id": inv_oid,
            "token": "abc",
            "status": "pendente",
            "expira_em": exp,
            "family_group_id": fg_oid,
        }
        mock_inv_coll.return_value = mock_inv
        mock_repo = mock_ur_cls.return_value
        mock_repo.find_by_id.return_value = {"_id": uid, "email": "n@e.com"}
        mock_repo.collection = MagicMock()
        mock_fgc = MagicMock()
        mock_fg_coll.return_value = mock_fgc
        mock_fgc.find_one.return_value = {
            "_id": fg_oid,
            "nome": "Família X",
            "members": [{"user_id": ObjectId()}],
            "limite_membros": 5,
        }

        out = accept_family_invite(uid, "abc")

        self.assertEqual(out["nome"], "Família X")
        self.assertEqual(out["family_group_id"], str(fg_oid))
        mock_fgc.update_one.assert_called_once()
        mock_repo.collection.update_one.assert_called_once()
        mock_inv.update_one.assert_called_once()

    @patch("core.services.family_invite_service.get_family_invites_collection")
    @patch("core.services.family_invite_service.get_family_groups_collection")
    @patch("core.services.family_invite_service.get_client")
    @patch("core.services.family_invite_service.UserRepository")
    def test_rollback_quando_falha_atualizar_usuario(
        self, mock_ur_cls, _gc, mock_fg_coll, mock_inv_coll
    ):
        uid = ObjectId()
        fg_oid = ObjectId()
        inv_oid = ObjectId()
        exp = datetime.utcnow() + timedelta(days=1)
        mock_inv = MagicMock()
        mock_inv.find_one.return_value = {
            "_id": inv_oid,
            "token": "abc",
            "status": "pendente",
            "expira_em": exp,
            "family_group_id": fg_oid,
        }
        mock_inv_coll.return_value = mock_inv
        mock_repo = mock_ur_cls.return_value
        mock_repo.find_by_id.return_value = {"_id": uid, "email": "n@e.com"}
        mock_ucol = MagicMock()
        mock_ucol.update_one.side_effect = RuntimeError("erro mongo user")
        mock_repo.collection = mock_ucol
        mock_fgc = MagicMock()
        mock_fg_coll.return_value = mock_fgc
        mock_fgc.find_one.return_value = {
            "_id": fg_oid,
            "nome": "Família X",
            "members": [{"user_id": ObjectId()}],
            "limite_membros": 5,
        }

        with self.assertRaises(RuntimeError):
            accept_family_invite(uid, "abc")

        self.assertEqual(mock_fgc.update_one.call_count, 2)
        first_kw = mock_fgc.update_one.call_args_list[0][0][1]
        self.assertIn("$push", first_kw)
        second_kw = mock_fgc.update_one.call_args_list[1][0][1]
        self.assertIn("$pull", second_kw)
        self.assertEqual(second_kw["$pull"]["members"]["user_id"], uid)
        mock_inv.update_one.assert_not_called()

    @patch("core.services.family_invite_service.get_family_invites_collection")
    @patch("core.services.family_invite_service.get_client")
    @patch("core.services.family_invite_service.UserRepository")
    def test_token_invalido(self, mock_ur_cls, _gc, mock_inv_coll):
        mock_inv_coll.return_value.find_one.return_value = None
        mock_ur_cls.return_value.find_by_id.return_value = {"_id": ObjectId()}
        with self.assertRaisesMessage(ValueError, "Convite inválido"):
            accept_family_invite(ObjectId(), "nope")

    @patch("core.services.family_invite_service.get_family_invites_collection")
    @patch("core.services.family_invite_service.get_client")
    @patch("core.services.family_invite_service.UserRepository")
    def test_token_ja_usado(self, mock_ur_cls, _gc, mock_inv_coll):
        mock_inv_coll.return_value.find_one.return_value = {
            "_id": ObjectId(),
            "status": "aceito",
            "token": "x",
            "expira_em": datetime.utcnow() + timedelta(days=1),
        }
        with self.assertRaisesMessage(ValueError, "Convite já utilizado"):
            accept_family_invite(ObjectId(), "x")

    @patch("core.services.family_invite_service.get_family_invites_collection")
    @patch("core.services.family_invite_service.get_client")
    @patch("core.services.family_invite_service.UserRepository")
    def test_token_expirado(self, mock_ur_cls, _gc, mock_inv_coll):
        mock_inv_coll.return_value.find_one.return_value = {
            "_id": ObjectId(),
            "status": "pendente",
            "token": "x",
            "expira_em": datetime.utcnow() - timedelta(hours=1),
        }
        with self.assertRaisesMessage(ValueError, "Convite expirado"):
            accept_family_invite(ObjectId(), "x")

    @patch("core.services.family_invite_service.get_family_invites_collection")
    @patch("core.services.family_invite_service.get_client")
    @patch("core.services.family_invite_service.UserRepository")
    def test_usuario_ja_em_familia(self, mock_ur_cls, _gc, mock_inv_coll):
        uid = ObjectId()
        mock_inv_coll.return_value.find_one.return_value = {
            "_id": ObjectId(),
            "status": "pendente",
            "token": "x",
            "expira_em": datetime.utcnow() + timedelta(days=1),
            "family_group_id": ObjectId(),
        }
        mock_ur_cls.return_value.find_by_id.return_value = {
            "_id": uid,
            "family_group_id": ObjectId(),
        }
        with self.assertRaisesMessage(
            ValueError, "Usuário já pertence a uma família"
        ):
            accept_family_invite(uid, "x")

    @patch("core.services.family_invite_service.get_family_groups_collection")
    @patch("core.services.family_invite_service.get_family_invites_collection")
    @patch("core.services.family_invite_service.get_client")
    @patch("core.services.family_invite_service.UserRepository")
    def test_limite_familia(
        self, mock_ur_cls, _gc, mock_inv_coll, mock_fg_coll
    ):
        uid = ObjectId()
        fg_oid = ObjectId()
        members = [{"user_id": ObjectId()} for _ in range(5)]
        mock_inv_coll.return_value.find_one.return_value = {
            "_id": ObjectId(),
            "status": "pendente",
            "token": "x",
            "expira_em": datetime.utcnow() + timedelta(days=1),
            "family_group_id": fg_oid,
        }
        mock_ur_cls.return_value.find_by_id.return_value = {"_id": uid}
        mock_fgc = MagicMock()
        mock_fg_coll.return_value = mock_fgc
        mock_fgc.find_one.return_value = {
            "_id": fg_oid,
            "members": members,
            "limite_membros": 5,
        }
        with self.assertRaisesMessage(
            ValueError, "Família atingiu o limite de membros do plano"
        ):
            accept_family_invite(uid, "x")

    @patch("core.services.family_invite_service.get_family_invites_collection")
    @patch("core.services.family_invite_service.get_family_groups_collection")
    @patch("core.services.family_invite_service.get_client")
    @patch("core.services.family_invite_service.UserRepository")
    def test_usuario_ja_membro_na_familia(
        self, mock_ur_cls, _gc, mock_fg_coll, mock_inv_coll
    ):
        uid = ObjectId()
        fg_oid = ObjectId()
        mock_inv_coll.return_value.find_one.return_value = {
            "_id": ObjectId(),
            "status": "pendente",
            "token": "tok",
            "expira_em": datetime.utcnow() + timedelta(days=1),
            "family_group_id": fg_oid,
        }
        mock_ur_cls.return_value.find_by_id.return_value = {"_id": uid}
        mock_fgc = MagicMock()
        mock_fg_coll.return_value = mock_fgc
        mock_fgc.find_one.return_value = {
            "_id": fg_oid,
            "nome": "F",
            "members": [
                {"user_id": ObjectId()},
                {"user_id": uid, "role": "member"},
            ],
            "limite_membros": 5,
        }
        with self.assertRaisesMessage(
            ValueError, "Usuário já é membro desta família"
        ):
            accept_family_invite(uid, "tok")


class UserReadScopeTests(SimpleTestCase):
    """Escopo de leitura (individual vs família) com Mongo mockado."""

    @patch.object(user_scope_mod, "get_family_groups_collection")
    @patch.object(user_scope_mod, "get_client")
    def test_sem_familia_apenas_user_id(
        self, _mock_client, mock_fg_coll
    ):
        uid = ObjectId()
        user = {"_id": uid}
        f, members = user_scope_mod.resolve_user_read_scope(user)
        self.assertEqual(f, {"user_id": uid})
        self.assertEqual(members, [uid])

    @patch.object(user_scope_mod, "get_family_groups_collection")
    @patch.object(user_scope_mod, "get_client")
    def test_familia_nao_encontrada_fallback_individual(
        self, _mock_client, mock_fg_coll
    ):
        uid = ObjectId()
        fg = ObjectId()
        user = {"_id": uid, "family_group_id": fg}
        mock_fg_coll.return_value.find_one.return_value = None
        f, members = user_scope_mod.resolve_user_read_scope(user)
        self.assertEqual(f, {"user_id": uid})
        self.assertEqual(members, [uid])

    @patch.object(user_scope_mod, "get_family_groups_collection")
    @patch.object(user_scope_mod, "get_client")
    def test_familia_agrega_membros(
        self, _mock_client, mock_fg_coll
    ):
        uid = ObjectId()
        other = ObjectId()
        fg = ObjectId()
        user = {"_id": uid, "family_group_id": fg}
        mock_fg_coll.return_value.find_one.return_value = {
            "_id": fg,
            "members": [{"user_id": other}, {"user_id": uid}],
        }
        f, members = user_scope_mod.resolve_user_read_scope(user)
        self.assertIn("$in", f["user_id"])
        self.assertEqual(set(f["user_id"]["$in"]), {uid, other})
        self.assertEqual(len(members), 2)
        self.assertEqual(set(members), {uid, other})

    def test_get_user_scope_filter_compativel_com_merge(self):
        uid = ObjectId()
        with patch.object(
            user_scope_mod, "resolve_user_read_scope"
        ) as mock_r:
            mock_r.return_value = ({"user_id": uid}, [uid])
            self.assertEqual(
                user_scope_mod.get_user_scope_filter({"_id": uid}),
                {"user_id": uid},
            )
