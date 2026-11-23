"""
Service para compromissos.

Localização: finance/services/compromisso_service.py

Lógica de negócio para gerenciamento de compromissos.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from finance.repositories.compromisso_repository import CompromissoRepository
from bson import ObjectId


class CompromissoService:
    """
    Service para gerenciar compromissos.
    """
    
    def __init__(self):
        self.repository = CompromissoRepository()
    
    def criar_compromisso(self, user_id: str, titulo: str, descricao: str, 
                         data: str, hora: str, hora_fim: str = None, tipo: str = None) -> Dict[str, Any]:
        """
        Cria um novo compromisso.
        
        Args:
            user_id: ID do usuário
            titulo: Título do compromisso
            descricao: Descrição do compromisso
            data: Data no formato YYYY-MM-DD
            hora: Hora de início no formato HH:MM
            hora_fim: Hora de término no formato HH:MM (obrigatório)
            tipo: Tipo do compromisso (opcional)
        
        Returns:
            Dict com o compromisso criado
        """
        if not user_id:
            raise ValueError("user_id é obrigatório")
        
        if not titulo or not titulo.strip():
            raise ValueError("Título é obrigatório")
        
        if not data:
            raise ValueError("Data é obrigatória")
        
        if not hora:
            raise ValueError("Hora de início é obrigatória")
        
        if not hora_fim:
            raise ValueError("Hora de término é obrigatória")
        
        # Validar que hora_fim é posterior a hora
        try:
            hora_parts = hora.split(':')
            hora_fim_parts = hora_fim.split(':')
            hora_minutos = int(hora_parts[0]) * 60 + int(hora_parts[1])
            hora_fim_minutos = int(hora_fim_parts[0]) * 60 + int(hora_fim_parts[1])
            
            if hora_fim_minutos <= hora_minutos:
                raise ValueError("O horário de término deve ser posterior ao horário de início")
        except ValueError:
            raise
        except:
            raise ValueError("Formato de horário inválido")
        
        compromisso_data = {
            'user_id': user_id,
            'titulo': titulo.strip(),
            'descricao': descricao.strip() if descricao else '',
            'data': data,
            'hora': hora.strip(),  # Compatibilidade
            'hora_inicio': hora.strip(),  # Novo campo
            'hora_fim': hora_fim.strip(),  # Novo campo
            'tipo': tipo.strip() if tipo else None,
            'status': 'pendente'
        }
        
        return self.repository.create(compromisso_data)
    
    def listar_compromissos(self, user_id: str, start_date: datetime = None, 
                           end_date: datetime = None) -> List[Dict[str, Any]]:
        """
        Lista compromissos de um usuário.
        
        Args:
            user_id: ID do usuário
            start_date: Data inicial (opcional)
            end_date: Data final (opcional)
        
        Returns:
            Lista de compromissos
        """
        if not user_id:
            raise ValueError("user_id é obrigatório")
        
        if start_date and end_date:
            return self.repository.find_by_user_and_period(user_id, start_date, end_date)
        else:
            return self.repository.find_by_user(user_id)
    
    def atualizar_compromisso(self, compromisso_id: str, user_id: str,
                             titulo: str = None, descricao: str = None,
                             data: str = None, hora: str = None, hora_fim: str = None,
                             tipo: str = None, status: str = None) -> Optional[Dict[str, Any]]:
        """
        Atualiza um compromisso.
        
        Args:
            compromisso_id: ID do compromisso
            user_id: ID do usuário (para validação de segurança)
            titulo: Novo título (opcional)
            descricao: Nova descrição (opcional)
            data: Nova data (opcional)
            hora: Nova hora (opcional)
            tipo: Novo tipo (opcional)
            status: Novo status (opcional)
        
        Returns:
            Compromisso atualizado ou None se não encontrado
        """
        # Verificar se o compromisso pertence ao usuário
        compromisso = self.repository.find_by_id(compromisso_id)
        if not compromisso:
            return None
        
        if str(compromisso.get('user_id')) != str(user_id):
            raise PermissionError("Você não tem permissão para editar este compromisso")
        
        update_data = {}
        if titulo is not None:
            update_data['titulo'] = titulo.strip()
        if descricao is not None:
            update_data['descricao'] = descricao.strip()
        if data is not None:
            update_data['data'] = data
        if hora is not None:
            update_data['hora'] = hora.strip()
            update_data['hora_inicio'] = hora.strip()  # Atualizar também hora_inicio
        if hora_fim is not None:
            update_data['hora_fim'] = hora_fim.strip()
            # Validar que hora_fim é posterior a hora se ambos foram fornecidos
            if hora is not None:
                try:
                    hora_parts = hora.strip().split(':')
                    hora_fim_parts = hora_fim.strip().split(':')
                    hora_minutos = int(hora_parts[0]) * 60 + int(hora_parts[1])
                    hora_fim_minutos = int(hora_fim_parts[0]) * 60 + int(hora_fim_parts[1])
                    
                    if hora_fim_minutos <= hora_minutos:
                        raise ValueError("O horário de término deve ser posterior ao horário de início")
                except ValueError:
                    raise
                except:
                    raise ValueError("Formato de horário inválido")
        if tipo is not None:
            update_data['tipo'] = tipo.strip() if tipo else None
        if status is not None:
            update_data['status'] = status
        
        return self.repository.update(compromisso_id, update_data)
    
    def excluir_compromisso(self, compromisso_id: str, user_id: str) -> bool:
        """
        Exclui um compromisso.
        
        Args:
            compromisso_id: ID do compromisso
            user_id: ID do usuário (para validação de segurança)
        
        Returns:
            True se excluído com sucesso
        """
        # Verificar se o compromisso pertence ao usuário
        compromisso = self.repository.find_by_id(compromisso_id)
        if not compromisso:
            return False
        
        if str(compromisso.get('user_id')) != str(user_id):
            raise PermissionError("Você não tem permissão para excluir este compromisso")
        
        return self.repository.delete(compromisso_id)
    
    def formatar_para_calendario(self, compromissos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Formata compromissos para o formato do FullCalendar.
        
        Args:
            compromissos: Lista de compromissos
        
        Returns:
            Lista formatada para FullCalendar
        """
        eventos = []
        
        for comp in compromissos:
            try:
                # Combinar data e hora
                data_str = comp.get('data')
                hora_str = comp.get('hora', '00:00')
                
                # Converter data se necessário
                if isinstance(data_str, datetime):
                    data_obj = data_str
                elif isinstance(data_str, str):
                    try:
                        data_obj = datetime.strptime(data_str, '%Y-%m-%d')
                    except:
                        # Tentar outros formatos
                        try:
                            data_obj = datetime.strptime(data_str, '%Y-%m-%d %H:%M:%S')
                        except:
                            from dateutil import parser
                            data_obj = parser.parse(data_str)
                            if data_obj.tzinfo:
                                data_obj = data_obj.astimezone().replace(tzinfo=None)
                else:
                    # Se for outro tipo (ex: date), converter
                    data_obj = datetime.combine(data_str, datetime.min.time())
                
                # Garantir que data_obj seja naive (sem timezone)
                if data_obj.tzinfo:
                    data_obj = data_obj.astimezone().replace(tzinfo=None)
                
                # Processar hora_inicio (priorizar hora_inicio, mas manter compatibilidade com 'hora')
                hora_inicio_str = comp.get('hora_inicio') or comp.get('hora', '00:00')
                hora_fim_str = comp.get('hora_fim', '')
                
                hora_parts = str(hora_inicio_str).split(':')
                hora_int = int(hora_parts[0]) if len(hora_parts) > 0 and hora_parts[0].isdigit() else 0
                minuto_int = int(hora_parts[1]) if len(hora_parts) > 1 and hora_parts[1].isdigit() else 0
                
                # Criar datetime combinado (naive, UTC)
                start_datetime = data_obj.replace(hour=hora_int, minute=minuto_int, second=0, microsecond=0)
                
                # Processar hora_fim se disponível
                if hora_fim_str:
                    hora_fim_parts = str(hora_fim_str).split(':')
                    hora_fim_int = int(hora_fim_parts[0]) if len(hora_fim_parts) > 0 and hora_fim_parts[0].isdigit() else hora_int
                    minuto_fim_int = int(hora_fim_parts[1]) if len(hora_fim_parts) > 1 and hora_fim_parts[1].isdigit() else minuto_int
                    end_datetime = data_obj.replace(hour=hora_fim_int, minute=minuto_fim_int, second=0, microsecond=0)
                else:
                    # Se não tiver hora_fim, usar 1 hora depois do início (compatibilidade)
                    end_datetime = start_datetime + timedelta(hours=1)
                
                # Cor para status
                status = comp.get('status', 'pendente')
                cores = {
                    'pendente': '#ffc107',
                    'confirmado': '#17a2b8',
                    'concluido': '#28a745',
                    'cancelado': '#dc3545'
                }
                cor = cores.get(status, '#6c757d')
                
                # Formatar data/hora para ISO (sem timezone para FullCalendar)
                start_iso = start_datetime.isoformat()
                end_iso = end_datetime.isoformat()
                
                evento = {
                    'id': str(comp.get('_id')),
                    'title': comp.get('titulo', 'Sem título'),
                    'start': start_iso,
                    'end': end_iso,
                    'description': comp.get('descricao', ''),
                    'backgroundColor': cor,
                    'borderColor': cor,
                    'textColor': '#ffffff',
                    'extendedProps': {
                        'tipo': comp.get('tipo'),
                        'status': status,
                        'hora': hora_str
                    }
                }
                eventos.append(evento)
                
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"[FORMATAR_CALENDARIO] Erro ao formatar compromisso {comp.get('_id')}: {e}", exc_info=True)
                # Continuar processando outros compromissos mesmo se um falhar
                continue
        
        return eventos
