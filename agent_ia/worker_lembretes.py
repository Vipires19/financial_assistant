"""
Lógica de lembretes migrada para Celery.

Para rodar o worker de lembretes, use:

  celery -A celery_app worker --loglevel=info

(Execute a partir da pasta agent_ia, ou use celery -A agent_ia.celery_app se estiver na raiz do projeto.)

Com agendamento a cada 5 minutos (Celery Beat):

  celery -A celery_app beat --loglevel=info
  celery -A celery_app worker --loglevel=info

Tasks: tasks.verificar_lembretes, tasks.enviar_confirmacao
"""
