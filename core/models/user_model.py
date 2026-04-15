"""
Modelo de usuário com suporte a roles e accounts (futuro).

Localização: core/models/user_model.py

Este módulo define a estrutura de dados do usuário no MongoDB,
incluindo suporte para roles e accounts (preparado para futuro).
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from bson import ObjectId


class UserModel:
    """
    Modelo de usuário com suporte a roles e accounts.
    
    Schema no MongoDB:
    {
      _id: ObjectId,
      email: String (único),
      password_hash: String,
      role: String,              // 'user', 'admin' (futuro: mais roles)
      account_id: ObjectId,      // ID da conta/organização (futuro)
      family_group_id: ObjectId | omitido | null,  // opcional — modo família (futuro)
      role_in_family: String | omitido | null,     // opcional — 'owner' | 'member'
      tipo_plano: String | omitido,                // 'individual' | 'familia' (recursos; preferir este campo)
      status_pagamento: String | omitido,          // ativo, cancelando, cancelado, pendente, ...
      cancelamento_agendado: Boolean | omitido,     // True = cancelou no MP; acesso até data_fim_acesso
      data_fim_acesso: ISODate | omitido | null,    // fim do período pago (grace); depois downgrade automático
      assinatura: {                                // pagamento (trial, mensal, anual — não confundir com tipo_plano)
        plano_key: String | omitido,               // chave canônica: mensal_individual, anual_familia, ...
        plano: String,
        status_pagamento: String | omitido,
        ...
      },
      is_active: Boolean,
      aceitou_termos: Boolean,
      data_aceite_termos: ISODate,
      versao_termos: String,     // ex: "1.0"
      created_at: ISODate,
      updated_at: ISODate
    }

    Campos ``family_group_id`` e ``role_in_family`` são opcionais; usuários sem eles
    seguem o fluxo atual sem alteração.
    """
    
    # Roles disponíveis
    ROLE_USER = 'user'
    ROLE_ADMIN = 'admin'

    # Modo família (opcional no documento; não confundir com ``role`` da aplicação)
    ROLE_IN_FAMILY_OWNER = 'owner'
    ROLE_IN_FAMILY_MEMBER = 'member'
    VALID_ROLES_IN_FAMILY = (ROLE_IN_FAMILY_OWNER, ROLE_IN_FAMILY_MEMBER)

    # Plano de recursos (monetização — individual vs família). Preferir campo ``tipo_plano`` no MongoDB.
    PLAN_INDIVIDUAL = "individual"
    PLAN_FAMILIA = "familia"
    VALID_PLANOS_RECURSOS = (PLAN_INDIVIDUAL, PLAN_FAMILIA)
    
    # Roles válidas
    VALID_ROLES = [ROLE_USER, ROLE_ADMIN]
    
    @staticmethod
    def create_user_data(email: str, password_hash: str, 
                        role: str = ROLE_USER,
                        account_id: Optional[str] = None,
                        **kwargs) -> Dict[str, Any]:
        """
        Cria estrutura de dados do usuário.
        
        Args:
            email: Email do usuário
            password_hash: Hash da senha
            role: Role do usuário (default: 'user')
            account_id: ID da conta/organização (opcional, futuro)
            **kwargs: Campos adicionais
        
        Returns:
            Dict com dados do usuário
        """
        if role not in UserModel.VALID_ROLES:
            role = UserModel.ROLE_USER
        
        user_data = {
            'email': email.lower().strip(),
            'password_hash': password_hash,
            'role': role,
            'is_active': True,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow(),
            **kwargs
        }
        
        # Adiciona account_id se fornecido (futuro)
        if account_id:
            user_data['account_id'] = ObjectId(account_id) if isinstance(account_id, str) else account_id
        
        return user_data
    
    @staticmethod
    def has_permission(user: Dict[str, Any], permission: str) -> bool:
        """
        Verifica se usuário tem permissão.
        
        Args:
            user: Dict com dados do usuário
            permission: Permissão a verificar
        
        Returns:
            True se usuário tem permissão
        """
        role = user.get('role', UserModel.ROLE_USER)
        
        # Admin tem todas as permissões
        if role == UserModel.ROLE_ADMIN:
            return True
        
        # Permissões específicas por role (futuro)
        permissions_map = {
            UserModel.ROLE_USER: ['view_own_data', 'create_transaction', 'generate_report'],
            UserModel.ROLE_ADMIN: ['*']  # Todas
        }
        
        user_permissions = permissions_map.get(role, [])
        return '*' in user_permissions or permission in user_permissions
    
    @staticmethod
    def get_plano_recursos(user: Optional[Dict[str, Any]]) -> str:
        """
        Retorna o plano de recursos: individual (default) ou familia.

        Delega para ``core.services.plan_service.get_plano_recursos`` (fonte única de verdade).
        """
        from core.services.plan_service import get_plano_recursos as _get_plano_recursos

        return _get_plano_recursos(user)

    @staticmethod
    def is_admin(user: Dict[str, Any]) -> bool:
        """
        Verifica se usuário é admin.
        
        Args:
            user: Dict com dados do usuário
        
        Returns:
            True se usuário é admin
        """
        return user.get('role') == UserModel.ROLE_ADMIN

