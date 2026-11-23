"""
Envio de emails via Resend API.

Localização: core/services/email_service.py
Não expõe erros internos nem token na resposta.
"""
import os
import logging
import requests
from dotenv import load_dotenv,find_dotenv
logger = logging.getLogger(__name__)

load_dotenv(find_dotenv())
RESEND_API_URL = "https://api.resend.com/emails"
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")

EMAIL_FROM = os.getenv("EMAIL_FROM", "Leozera <onboarding@resend.dev>")


def send_email_verificacao(email: str, link_verificacao: str) -> bool:
    """
    Envia email de confirmação com botão/link para verificar email.
    link_verificacao: URL absoluta para /verificar-email/<token>
    Retorna True se enviado com sucesso, False caso contrário (nunca levanta exceção).
    """
    if not RESEND_API_KEY:
        logger.warning("[EMAIL] RESEND_API_KEY não configurada; email de verificação não enviado.")
        return False
    subject = "Confirme seu email - Leozera"
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #0369a1;">Confirme seu email</h2>
        <p>Olá,</p>
        <p>Para ativar sua conta no Leozera, confirme seu email clicando no botão abaixo:</p>
        <p style="margin: 28px 0;">
            <a href="{link_verificacao}" style="background: #0284c7; color: #fff; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Confirmar email</a>
        </p>
        <p style="color: #666; font-size: 14px;">Este link expira em 10 minutos. Se você não criou esta conta, ignore este email.</p>
        <p style="color: #666; font-size: 14px;">— Equipe Leozera</p>
    </body>
    </html>
    """
    return _send(email, subject, html)


def send_email_recuperacao(email: str, link_resetar: str) -> bool:
    """
    Envia email de recuperação de senha com link para resetar.
    link_resetar: URL absoluta para /resetar-senha/<token>
    Retorna True se enviado, False caso contrário.
    """
    if not RESEND_API_KEY:
        logger.warning("[EMAIL] RESEND_API_KEY não configurada; email de recuperação não enviado.")
        return False
    subject = "Recuperação de senha - Leozera"
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #0369a1;">Recuperação de senha</h2>
        <p>Olá,</p>
        <p>Você solicitou a redefinição de senha. Clique no botão abaixo para criar uma nova senha:</p>
        <p style="margin: 28px 0;">
            <a href="{link_resetar}" style="background: #0284c7; color: #fff; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Redefinir senha</a>
        </p>
        <p style="color: #666; font-size: 14px;">Este link expira em 10 minutos. Se você não pediu isso, ignore este email.</p>
        <p style="color: #666; font-size: 14px;">— Equipe Leozera</p>
    </body>
    </html>
    """
    return _send(email, subject, html)


def send_email_novo_email(email_destino: str, link_confirmacao: str) -> bool:
    """
    Envia email para confirmar alteração de email (novo endereço).
    link_confirmacao: URL absoluta para /confirmar-novo-email/<token>
    Retorna True se enviado, False caso contrário.
    """
    if not RESEND_API_KEY:
        logger.warning("[EMAIL] RESEND_API_KEY não configurada; email de confirmação de novo email não enviado.")
        return False
    subject = "Confirme seu novo email - Leozera"
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #0369a1;">Confirme seu novo email</h2>
        <p>Olá,</p>
        <p>Você solicitou a alteração do email da sua conta. Para confirmar o novo endereço, clique no botão abaixo:</p>
        <p style="margin: 28px 0;">
            <a href="{link_confirmacao}" style="background: #0284c7; color: #fff; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Confirmar novo email</a>
        </p>
        <p style="color: #666; font-size: 14px;">Este link expira em 10 minutos. Se você não solicitou essa alteração, ignore este email.</p>
        <p style="color: #666; font-size: 14px;">— Equipe Leozera</p>
    </body>
    </html>
    """
    return _send(email_destino, subject, html)


def _send(to: str, subject: str, html: str) -> bool:
    """POST para Resend. Retorna True se 2xx, False caso contrário. Nunca expõe erro interno."""
    try:
        r = requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": EMAIL_FROM,
                "to": [to],
                "subject": subject,
                "html": html,
            },
            timeout=10,
        )
        if r.status_code >= 200 and r.status_code < 300:
            return True
        logger.warning("[EMAIL] Resend retornou status %s", r.status_code)
        return False
    except Exception as e:
        logger.exception("[EMAIL] Erro ao enviar: %s", e)
        return False
