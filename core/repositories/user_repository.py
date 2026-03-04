"""
Repository para operações de usuário no MongoDB.

Localização: core/repositories/user_repository.py

Encapsula todas as operações com a collection 'users' no MongoDB.
"""
from typing import Optional, Dict, Any
from core.repositories.base_repository import BaseRepository
from core.database import get_database
import bcrypt
from datetime import datetime, timedelta


class UserRepository(BaseRepository):
    """
    Repository para gerenciar usuários no MongoDB.
    
    Exemplo de uso:
        repo = UserRepository()
        user = repo.create('user@email.com', 'senha123')
    """
    
    def __init__(self):
        super().__init__('users')
    
    def _ensure_indexes(self):
        """Cria índices necessários."""
        self.collection.create_index('email', unique=True)
    
    def create(self, email: str, password: str, role: str = 'user',
              account_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        Cria um novo usuário.
        
        Args:
            email: Email do usuário
            password: Senha em texto plano (será hasheada)
            role: Role do usuário ('user' ou 'admin', default: 'user')
            account_id: ID da conta/organização (opcional, futuro)
            **kwargs: Campos adicionais do usuário
        
        Returns:
            Dict com os dados do usuário criado (sem password_hash)
        """
        # Hash da senha com bcrypt
        hashed_password = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')
        
        # Valida role
        valid_roles = ['user', 'admin']
        if role not in valid_roles:
            role = 'user'
        
        # Categorias pré-definidas - sempre populadas ao criar usuário
        from finance.models.categoria_model import CategoriaModel
        categorias_predefinidas = CategoriaModel.get_categorias_predefinidas()
        
        user_data = {
            'email': email.lower().strip(),
            'password_hash': hashed_password,
            'role': role,
            'is_active': True,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow(),
            **kwargs
        }
        
        # Se categorias já vierem em kwargs, usa elas (permite sobrescrever)
        # Caso contrário, popula com categorias pré-definidas
        if 'categorias' not in kwargs or not kwargs.get('categorias'):
            user_data['categorias'] = categorias_predefinidas
        else:
            user_data['categorias'] = kwargs['categorias']

        # Contas padrão (não sobrescreve se vier em kwargs)
        if 'contas' not in kwargs:
            user_data['contas'] = [
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
        else:
            user_data['contas'] = kwargs['contas']
        
        # Adiciona account_id se fornecido (futuro)
        if account_id:
            from bson import ObjectId
            user_data['account_id'] = ObjectId(account_id) if isinstance(account_id, str) else account_id
        
        # GARANTIA FINAL: Verifica se categorias foram populadas antes de salvar
        if 'categorias' not in user_data or not user_data.get('categorias'):
            user_data['categorias'] = CategoriaModel.get_categorias_predefinidas()

        # Assinatura padrão: novo usuário inicia em trial de 7 dias (não sobrescreve se vier em kwargs)
        if 'assinatura' not in kwargs:
            now = datetime.utcnow()
            user_data['assinatura'] = {
                'plano': 'trial',
                'status': 'ativa',
                'inicio': now,
                'fim': now + timedelta(days=7),
                'renovacao_automatica': False,
                'gateway': None,
                'gateway_subscription_id': None,
                'ultimo_pagamento_em': None,
                'proximo_vencimento': None,
            }

        # Timezone fixo (não sobrescreve se já veio em kwargs)
        if 'timezone' not in user_data:
            user_data['timezone'] = 'America/Sao_Paulo'

        # Verificação de email: novo usuário inicia não verificado (não sobrescreve se vier em kwargs)
        if 'email_verificado' not in user_data:
            user_data['email_verificado'] = False

        # Salva o usuário no MongoDB
        result = self.collection.insert_one(user_data)
        user_data['_id'] = result.inserted_id
        
        # Remove senha do retorno
        user_data.pop('password_hash', None)
        return user_data
    
    def _normalize_user_legacy(self, user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Compatibilidade: se usuário antigo sem campo 'plano', define defaults e persiste no DB.
        Não sobrescreve quem já tem plano definido.
        Leitura: assinatura primeiro, depois campos antigos. Escrita: dual write (assinatura + antigos).
        """
        assinatura = (user or {}).get('assinatura') or {}
        tem_plano = 'plano' in (user or {}) or assinatura.get('plano') is not None
        if not user or tem_plano:
            return user
        from bson import ObjectId
        self.collection.update_one(
            {'_id': user['_id']},
            {'$set': {
                'plano': 'sem_plano',
                'status_assinatura': 'vencida',
                'assinatura.plano': 'sem_plano',
                'assinatura.status': 'vencida',
                'updated_at': datetime.utcnow(),
            }}
        )
        user['plano'] = 'sem_plano'
        user['status_assinatura'] = 'vencida'
        if 'assinatura' not in user:
            user['assinatura'] = {}
        user['assinatura']['plano'] = 'sem_plano'
        user['assinatura']['status'] = 'vencida'
        return user

    def find_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Busca usuário por email.
        
        Args:
            email: Email do usuário
        
        Returns:
            Dict com dados do usuário ou None
        """
        user = self.collection.find_one({'email': email.lower().strip()})
        if user:
            user = self._normalize_user_legacy(user)
        return user

    def find_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca usuário por ID.
        
        Args:
            user_id: ID do usuário (ObjectId como string)
        
        Returns:
            Dict com dados do usuário ou None (sem password_hash)
        """
        from bson import ObjectId
        try:
            user = self.collection.find_one({'_id': ObjectId(user_id)})
            if user:
                user.pop('password_hash', None)
                user = self._normalize_user_legacy(user)
            return user
        except Exception:
            return None
    
    def verify_password(self, email: str, password: str) -> bool:
        """
        Verifica se a senha está correta.
        
        Args:
            email: Email do usuário
            password: Senha em texto plano
        
        Returns:
            True se a senha estiver correta, False caso contrário
        """
        user = self.find_by_email(email)
        if not user or 'password_hash' not in user:
            return False
        
        try:
            return bcrypt.checkpw(
                password.encode('utf-8'),
                user['password_hash'].encode('utf-8')
            )
        except:
            return False

    def verify_password_by_id(self, user_id: str, password: str) -> bool:
        """
        Verifica se a senha está correta para o usuário pelo ID.
        Usado na página de configurações (alteração de senha).
        """
        from bson import ObjectId
        try:
            user = self.collection.find_one(
                {'_id': ObjectId(user_id)},
                {'password_hash': 1}
            )
            if not user or 'password_hash' not in user:
                return False
            return bcrypt.checkpw(
                password.encode('utf-8'),
                user['password_hash'].encode('utf-8')
            )
        except Exception:
            return False

    def find_by_token_novo_email(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Busca usuário pelo token de confirmação de novo email.
        Retorna o usuário apenas se token_novo_email_expira_em > agora (UTC).
        """
        from datetime import timezone
        now = datetime.now(timezone.utc)
        user = self.collection.find_one({'token_novo_email': token})
        if not user:
            return None
        expira = user.get('token_novo_email_expira_em')
        if not expira:
            return None
        if getattr(expira, 'tzinfo', None) is None:
            expira = expira.replace(tzinfo=timezone.utc)
        if expira < now:
            return None
        user.pop('password_hash', None)
        return user

    def update(self, user_id: str, **kwargs) -> bool:
        """
        Atualiza dados do usuário.
        
        Args:
            user_id: ID do usuário
            **kwargs: Campos a atualizar
        
        Returns:
            True se atualizado com sucesso
        """
        from bson import ObjectId
        
        kwargs['updated_at'] = datetime.utcnow()
        result = self.collection.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': kwargs}
        )
        return result.modified_count > 0

    def find_by_token_confirmacao(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Busca usuário pelo token de confirmação (reenvio).
        Retorna o usuário apenas se token_expira_em > agora (UTC).
        """
        from datetime import timezone
        now = datetime.now(timezone.utc)
        user = self.collection.find_one({'token_confirmacao': token})
        if not user:
            return None
        expira = user.get('token_expira_em')
        if not expira:
            return None
        if getattr(expira, 'tzinfo', None) is None:
            expira = expira.replace(tzinfo=timezone.utc)
        if expira < now:
            return None
        user.pop('password_hash', None)
        return user

