"""
Views do app core.

Localização: core/views.py

Views são os controllers da aplicação. Elas:
- Recebem requisições HTTP
- Chamam services para lógica de negócio
- Retornam respostas (HTML, JSON, etc.)

NÃO devem conter lógica de negócio, apenas orquestração.
"""
import json
import logging
import uuid
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.urls import reverse
from django.http import JsonResponse
from datetime import datetime, timezone, timedelta
import os
import urllib.parse
from core.services.auth_service import AuthService
from core.decorators.auth import login_required_mongo
from core.services.audit_log_service import AuditLogService
from core.repositories.email_token_repository import EmailTokenRepository
from core.services.email_service import send_email_verificacao, send_email_recuperacao, send_email_novo_email
from core.services.family_group_service import create_family_group
from core.services.family_invite_service import create_family_invite, accept_family_invite
from core.services.family_ui_service import build_family_api_detail, get_family_hub_context
from core.models.user_model import UserModel
from core.repositories.user_repository import UserRepository
from core.services.mercadopago_service import (
    codigo_plano_valido,
    criar_assinatura,
    executar_cancelamento_pelo_usuario,
    extrair_preapproval_id_do_webhook,
    processar_webhook_preapproval,
)
from core.services.plan_service import (
    PLAN_FAMILIA,
    PLAN_INDIVIDUAL,
    get_plano_recursos as get_plano_recursos_svc,
    is_family_read_only,
    validate_tipo_plano_individual,
)
from bson import ObjectId


logger = logging.getLogger(__name__)


@require_GET
@login_required_mongo
def planos_view(request):
    """Página de planos do Leozera. Layout SaaS premium, preparada para integração futura com gateway."""
    cta = request.GET.get("upgrade_cta")
    if cta:
        logger.info(
            "event=upgrade_clicked source=%s user_id=%s",
            cta,
            request.session.get("user_id"),
        )
    return render(request, "core/planos.html")


@require_POST
@login_required_mongo
def escolher_plano_recursos_view(request):
    """
    POST /planos/recursos/ — define ``tipo_plano`` (individual | familia) e ``status_pagamento``.

    Alinha billing futuro: família ativa marca pagamento como ativo (manual até o gateway).
    Downgrade para individual exige sair da família antes.
    """
    if not getattr(request, "user_mongo", None):
        return redirect("core:login")
    raw = (request.POST.get("tipo_plano") or "").strip().lower()
    if raw not in (PLAN_INDIVIDUAL, PLAN_FAMILIA):
        messages.error(request, "Seleção de plano inválida.")
        return redirect("core:planos")
    uid = request.user_mongo["_id"]
    repo = UserRepository()
    user = repo.find_by_id(str(uid))
    if raw == PLAN_INDIVIDUAL:
        try:
            validate_tipo_plano_individual(user)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect(reverse("core:planos"))
    now = datetime.utcnow()
    payload = {
        "tipo_plano": raw,
        "status_pagamento": "ativo",
        "updated_at": now,
    }
    repo.collection.update_one({"_id": uid}, {"$set": payload})
    if raw == PLAN_FAMILIA:
        request.session["post_upgrade_familia"] = True
        return redirect(reverse("core:family_create"))
    messages.success(request, "Plano individual ativado.")
    return redirect(reverse("core:planos"))


@require_POST
def assinar_plano_view(request):
    """
    Placeholder para integração futura com gateway de pagamento.
    Recebe plano (mensal/anual) via POST. Por ora redireciona para /planos.
    """
    # TODO: Integrar com gateway (Stripe, Mercado Pago, etc.)
    messages.info(request, 'Integração com pagamento em breve. Entre em contato pelo WhatsApp para assinar.')
    return redirect('core:planos')


def _safe_next_url(url):
    """Permite apenas next interno (evita open redirect)."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url.startswith("/") or url.startswith("//") or len(url) > 512:
        return None
    return url


def is_safe_url(request, target):
    """
    Verifica se target é uma URL segura para redirecionamento (evita open redirect).
    Aceita path relativo (/checkout/mensal/) ou URL absoluta do mesmo host.
    """
    if not target or not isinstance(target, str):
        return False
    target = target.strip()
    if len(target) > 512:
        return False
    # Path relativo: só permitir /... sem // (evita protocol-relative)
    if target.startswith("/") and not target.startswith("//"):
        return True
    from urllib.parse import urlparse
    ref_url = urlparse(request.build_absolute_uri("/"))
    test_url = urlparse(target)
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


@require_GET
def iniciar_assinatura_view(request, plano):
    """
    GET /assinar/<plano>
    Rota intermediária: se não logado, redireciona para login com next=/checkout/<plano>/.
    Se logado, redireciona para /checkout/<plano>/.
    """
    if not codigo_plano_valido(plano):
        messages.error(request, "Plano inválido.")
        return redirect("core:planos")
    if not request.session.get("user_id"):
        from urllib.parse import quote
        next_path = reverse("core:pagina_checkout", kwargs={"plano": plano})
        login_url = reverse("core:login") + "?next=" + quote(next_path, safe="")
        return redirect(login_url)
    return redirect("core:pagina_checkout", plano=plano)


@require_GET
@login_required_mongo
def pagina_checkout_view(request, plano):
    """
    GET /checkout/<plano>
    Chama a lógica de assinatura (session) e redireciona para o checkout do Mercado Pago ou exibe erro.
    """
    if not codigo_plano_valido(plano):
        return render(request, "core/erro_pagamento.html", {"mensagem": "Plano inválido."})
    user_id = request.session.get("user_id")
    if not user_id:
        return redirect(reverse("core:login") + "?next=" + request.path)
    repo = UserRepository()
    user = repo.find_by_id(str(user_id))
    if not user:
        return render(
            request,
            "core/erro_pagamento.html",
            {"mensagem": "Usuário não encontrado."},
        )
    back = request.build_absolute_uri(reverse("core:pos_pagamento"))
    try:
        result = criar_assinatura(user, plano, back_url=back)
    except ValueError as e:
        return render(request, "core/erro_pagamento.html", {"mensagem": str(e)})
    except RuntimeError as e:
        return render(
            request,
            "core/erro_pagamento.html",
            {"mensagem": str(e) or "Erro ao iniciar assinatura."},
        )
    return redirect(result["init_point"])


@require_POST
@login_required_mongo
def api_assinar_plano_view(request, plano):
    """
    POST /api/assinar/<plano>
    Apenas sessão. Cria preapproval no Mercado Pago e retorna checkout_url.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return JsonResponse(
            {"error": "Não autenticado", "message": "É necessário fazer login para assinar."},
            status=401,
        )
    if not codigo_plano_valido(plano):
        return JsonResponse(
            {
                "error": "Plano inválido",
                "message": "Use mensal_individual, anual_individual, mensal_familia, anual_familia (ou mensal/anual).",
            },
            status=400,
        )
    repo = UserRepository()
    user = repo.find_by_id(str(user_id))
    if not user:
        return JsonResponse(
            {"error": "Usuário não encontrado", "message": "Usuário não encontrado"},
            status=404,
        )
    back = request.build_absolute_uri(reverse("core:pos_pagamento"))
    try:
        result = criar_assinatura(user, plano, back_url=back)
    except ValueError as e:
        return JsonResponse(
            {"error": str(e), "message": str(e)},
            status=400,
        )
    except RuntimeError as e:
        return JsonResponse(
            {"error": "Mercado Pago", "message": str(e)},
            status=502,
        )
    return JsonResponse({"checkout_url": result["init_point"]})


@require_POST
@login_required_mongo
def api_planos_assinar_view(request):
    """
    POST /api/planos/assinar/

    Body JSON: {"plano": "mensal_individual"|"anual_individual"|"mensal_familia"|"anual_familia"|"mensal"|"anual"}
    Retorna checkout_url (init_point) do Mercado Pago.
    """
    if not getattr(request, "user_mongo", None):
        return JsonResponse(
            {"error": "Não autenticado", "message": "É necessário fazer login para assinar."},
            status=401,
        )
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)
    plano = (data.get("plano") or request.POST.get("plano") or "").strip().lower()
    if not codigo_plano_valido(plano):
        return JsonResponse(
            {
                "error": "Plano inválido",
                "message": "Use mensal_individual, anual_individual, mensal_familia, anual_familia (ou mensal/anual).",
            },
            status=400,
        )
    back = request.build_absolute_uri(reverse("core:pos_pagamento"))
    try:
        result = criar_assinatura(request.user_mongo, plano, back_url=back)
    except ValueError as e:
        return JsonResponse({"error": str(e), "message": str(e)}, status=400)
    except RuntimeError as e:
        return JsonResponse(
            {"error": "Mercado Pago", "message": str(e)},
            status=502,
        )
    return JsonResponse({"checkout_url": result["init_point"]})


@require_POST
@login_required_mongo
def api_planos_cancelar_view(request):
    """
    POST /api/planos/cancelar/

    Cancela preapproval no Mercado Pago e agenda fim de acesso (grace).
    Body vazio ou JSON opcional (ignorado).
    """
    if not getattr(request, "user_mongo", None):
        return JsonResponse(
            {"success": False, "message": "É necessário fazer login."},
            status=401,
        )
    try:
        result = executar_cancelamento_pelo_usuario(request.user_mongo)
    except ValueError as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)
    except RuntimeError as e:
        return JsonResponse(
            {"success": False, "message": str(e) or "Erro ao cancelar no Mercado Pago."},
            status=502,
        )
    return JsonResponse(result)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def mercadopago_webhook_view(request):
    """
    POST /api/mercadopago/webhook/

    Notificações MP: valida preapproval via API antes de ativar plano.
    """
    if request.method == "GET":
        topic = (request.GET.get("topic") or "").lower()
        pid = request.GET.get("id") or request.GET.get("data.id")
        if topic == "preapproval" and pid:
            processar_webhook_preapproval(str(pid))
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        payload = {}

    event = str(payload.get("type") or payload.get("action") or "").lower()
    if event == "payment":
        return JsonResponse({"ok": True, "ignored": True})

    pid = extrair_preapproval_id_do_webhook(payload)
    if not pid:
        return JsonResponse({"ok": True, "ignored": True})

    if event and "preapproval" not in event and "subscription" not in event:
        return JsonResponse({"ok": True, "ignored": True})

    processar_webhook_preapproval(pid)
    return JsonResponse({"ok": True})


@require_GET
@login_required_mongo
def pos_pagamento_view(request):
    """GET /pos-pagamento/ — retorno após fluxo MP (ativação efetiva via webhook)."""
    return render(request, "core/pos_pagamento.html")


@require_POST
@login_required_mongo
def family_create_api_view(request):
    """
    POST /api/family/create/

    Body JSON: {"nome": "Família Silva"}

    Cria um ``family_group``, define o usuário autenticado como owner e membro.
    """
    if not getattr(request, "user_mongo", None):
        return JsonResponse(
            {"error": "Não autenticado", "message": "É necessário fazer login."},
            status=401,
        )
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    nome = data.get("nome")
    try:
        result = create_family_group(request.user_mongo["_id"], nome)
    except ValueError as e:
        msg = str(e)
        return JsonResponse({"error": msg, "message": msg}, status=400)

    return JsonResponse(result, json_dumps_params={"ensure_ascii": False})


@require_POST
@login_required_mongo
def family_invite_api_view(request):
    """
    POST /api/family/invite/

    Body JSON: {"nome": "Lorena", "telefone": "16999999999"}
    """
    if not getattr(request, "user_mongo", None):
        return JsonResponse(
            {"error": "Não autenticado", "message": "É necessário fazer login."},
            status=401,
        )
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    nome = data.get("nome")
    telefone = data.get("telefone")
    signup_base = request.build_absolute_uri("/").rstrip("/")
    try:
        result = create_family_invite(
            request.user_mongo["_id"],
            nome,
            telefone,
            signup_base_url=signup_base,
        )
    except ValueError as e:
        msg = str(e)
        return JsonResponse({"error": msg, "message": msg}, status=400)

    return JsonResponse(result, json_dumps_params={"ensure_ascii": False})


@require_POST
@login_required_mongo
def family_accept_api_view(request):
    """
    POST /api/family/accept/

    Body JSON: {"token": "abc123"}

    Vincula o usuário autenticado à família do convite (fallback se não usou token no cadastro).
    """
    if not getattr(request, "user_mongo", None):
        return JsonResponse(
            {"error": "Não autenticado", "message": "É necessário fazer login."},
            status=401,
        )
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    token = data.get("token")
    try:
        result = accept_family_invite(request.user_mongo["_id"], token)
    except ValueError as e:
        msg = str(e)
        return JsonResponse({"error": msg, "message": msg}, status=400)

    return JsonResponse(result, json_dumps_params={"ensure_ascii": False})


@require_GET
@login_required_mongo
def user_session_api_view(request):
    """
    GET /api/user/session/

    Plano de recursos (individual | familia) e campos preparados para cobrança futura.
    """
    if not getattr(request, "user_mongo", None):
        return JsonResponse(
            {"error": "Não autenticado", "message": "É necessário fazer login."},
            status=401,
        )
    u = request.user_mongo
    assinatura = u.get("assinatura") or {}
    plano_recursos = get_plano_recursos_svc(u)
    status_pagamento = assinatura.get("status_pagamento")
    if status_pagamento is None:
        status_pagamento = u.get("status_pagamento")
    return JsonResponse(
        {
            "plano": plano_recursos,
            "status_pagamento": status_pagamento,
            "assinatura": assinatura,
            "family_read_only": is_family_read_only(u),
        },
        json_dumps_params={"ensure_ascii": False},
    )


@require_POST
@login_required_mongo
def upgrade_familia_api_view(request):
    """
    POST /api/planos/upgrade-familia/

    Simula upgrade para plano família (sem gateway). Atualiza Mongo e retorna JSON.
    """
    if not getattr(request, "user_mongo", None):
        return JsonResponse(
            {"success": False, "error": "Não autenticado", "message": "É necessário fazer login."},
            status=401,
        )
    uid = request.user_mongo["_id"]
    repo = UserRepository()
    now = datetime.utcnow()
    repo.collection.update_one(
        {"_id": uid},
        {
            "$set": {
                "tipo_plano": PLAN_FAMILIA,
                "status_pagamento": "ativo",
                "updated_at": now,
            }
        },
    )
    logger.info("event=upgrade_completed user_id=%s", uid)
    request.session["post_upgrade_familia"] = True
    return JsonResponse(
        {
            "success": True,
            "message": "Plano família ativado com sucesso!",
        }
    )


@require_GET
@login_required_mongo
def family_detail_api_view(request):
    """
    GET /api/family/

    Retorna dados da família do usuário (ou has_family: false).
    """
    if not getattr(request, "user_mongo", None):
        return JsonResponse(
            {"error": "Não autenticado", "message": "É necessário fazer login."},
            status=401,
        )
    return JsonResponse(
        build_family_api_detail(request.user_mongo),
        json_dumps_params={"ensure_ascii": False},
    )


@require_GET
@login_required_mongo
def family_hub_view(request):
    """GET /family/ — Minha família ou empty state."""
    ctx = get_family_hub_context(request.user_mongo)
    return render(request, "core/family.html", ctx)


@require_http_methods(["GET", "POST"])
@login_required_mongo
def family_create_view(request):
    """GET/POST /family/criar/ — Criar família (redirect se já tiver)."""
    if not getattr(request, "user_mongo", None):
        return redirect("core:login")
    if request.user_mongo.get("family_group_id"):
        messages.info(request, "Você já está em uma família.")
        return redirect("core:family")
    if request.session.pop("post_upgrade_familia", False):
        messages.success(
            request,
            "🎉 Agora você pode criar sua família! Convide pessoas e comece a organizar tudo em conjunto.",
        )
        return redirect(reverse("core:family_create"))
    if request.method == "POST":
        nome = (request.POST.get("nome") or "").strip()
        try:
            create_family_group(request.user_mongo["_id"], nome)
            messages.success(request, "🎉 Família criada com sucesso!")
            return redirect("core:family")
        except ValueError as e:
            messages.error(request, str(e))
    return render(request, "core/family_create.html", {"user": request.user_mongo})


@require_GET
def termos_de_uso_view(request):
    """Página pública com o texto dos Termos de Uso (sem login obrigatório)."""
    return render(request, 'termos_de_uso.html')


@require_GET
def politica_privacidade_view(request):
    """Página pública com a Política de Privacidade (sem login obrigatório)."""
    return render(request, 'politica_privacidade.html')


@require_GET
def landing_view(request):
    """Landing page pública do Leozera (conversão para teste grátis)."""
    return render(request, 'landing.html')


def index_view(request):
    """View principal do dashboard (requer autenticação)."""
    # O middleware já adiciona request.user_mongo se autenticado
    if hasattr(request, 'user_mongo') and request.user_mongo:
        return render(request, 'core/dashboard.html', {
            'user': request.user_mongo
        })
    return redirect('core:login')


@require_http_methods(["GET", "POST"])
def login_view(request):
    """
    View de login.
    
    GET: Exibe formulário de login
    POST: Processa login
    """
    # Bloqueia acesso se já estiver logado
    if request.session.get('user_id'):
        next_url = request.GET.get("next")
        if next_url and is_safe_url(request, next_url):
            return redirect(next_url)
        return redirect("/finance/dashboard/")
    
    audit_service = AuditLogService()
    
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        
        auth_service = AuthService()
        user = auth_service.authenticate(email, password)
        
        if user:
            if not user.get('email_verificado', True):
                from urllib.parse import quote
                email_param = quote(request.POST.get('email', '').strip(), safe='')
                return redirect(reverse('core:email_nao_confirmado') + '?email=' + email_param)
            if '_id' not in user:
                messages.error(request, 'Erro interno: usuário sem ID')
                return render(request, 'core/login.html')
            request.session['user_id'] = str(user['_id'])
            request.session['user_email'] = user['email']
            audit_service.log_login(
                user_id=str(user['_id']),
                source='dashboard',
                status='success'
            )
            messages.success(request, f'Bem-vindo, {user["email"]}!')
            next_url = request.GET.get("next")
            if next_url and is_safe_url(request, next_url):
                return redirect(next_url)
            return redirect("/finance/dashboard/")
        else:
            # Loga tentativa de login falha
            # Não temos user_id, então loga sem user_id
            audit_service.log_action(
                user_id=None,
                action='login',
                entity='user',
                source='dashboard',
                status='error',
                payload={'email': email},
                error='Email ou senha incorretos'
            )
            
            messages.error(request, 'Email ou senha incorretos.')
    
    return render(request, 'core/login.html')


@require_http_methods(["GET", "POST"])
def register_view(request):
    """
    View de registro.
    
    GET: Exibe formulário de registro
    POST: Processa registro
    
    Convite modo família: GET ``/register/?token=...`` (campo oculto no POST).
    """
    # Se já estiver logado, redireciona
    if hasattr(request, 'user_mongo') and request.user_mongo:
        return redirect('core:index')

    if request.method == 'POST':
        family_invite_token = (request.POST.get('family_invite_token') or '').strip()
    else:
        family_invite_token = (request.GET.get('token') or '').strip()
    
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        nome = request.POST.get('nome', '').strip()
        telefone = request.POST.get('telefone', '').strip()
        cidade = request.POST.get('cidade', '').strip()
        estado = request.POST.get('estado', '').strip()

        # Validação dos campos obrigatórios
        if not nome:
            messages.error(request, 'Nome é obrigatório.')
            return render(request, 'core/register.html', {
                'email': email,
                'telefone': telefone,
                'cidade': cidade,
                'estado': estado,
                'family_invite_token': family_invite_token,
            })

        if not telefone:
            messages.error(request, 'Telefone é obrigatório.')
            return render(request, 'core/register.html', {
                'email': email,
                'nome': nome,
                'cidade': cidade,
                'estado': estado,
                'family_invite_token': family_invite_token,
            })

        if password != password_confirm:
            messages.error(request, 'As senhas não coincidem.')
            return render(request, 'core/register.html', {
                'email': email,
                'nome': nome,
                'telefone': telefone,
                'cidade': cidade,
                'estado': estado,
                'family_invite_token': family_invite_token,
            })

        if not request.POST.get('aceite_termos'):
            messages.error(request, 'É necessário aceitar os Termos de Uso para criar uma conta.')
            return render(request, 'core/register.html', {
                'email': email,
                'nome': nome,
                'telefone': telefone,
                'cidade': cidade,
                'estado': estado,
                'family_invite_token': family_invite_token,
            })

        auth_service = AuthService()
        try:
            user = auth_service.register(
                email,
                password,
                nome=nome,
                telefone=telefone,
                cidade=cidade or None,
                estado=estado or None,
                timezone='America/Sao_Paulo',
                aceitou_termos=True,
                data_aceite_termos=datetime.utcnow(),
                versao_termos='1.0',
            )
            if '_id' not in user:
                from django.http import HttpResponseServerError
                return HttpResponseServerError('Erro interno: usuário criado sem ID')

            if family_invite_token:
                try:
                    accept_family_invite(ObjectId(str(user['_id'])), family_invite_token)
                except ValueError as inv_err:
                    logger.warning(
                        "Convite família não aplicado após cadastro: %s", inv_err
                    )
                    messages.warning(request, str(inv_err))
                except Exception:
                    logger.exception(
                        "Erro inesperado ao aceitar convite família após cadastro"
                    )
                    messages.warning(
                        request,
                        'Não foi possível vincular o convite à família. Tente aceitar o convite novamente após confirmar o email.',
                    )

            token = str(uuid.uuid4())
            token_repo = EmailTokenRepository()
            token_repo.create(
                user_id=str(user['_id']),
                email=user['email'],
                token=token,
                tipo='verificacao',
            )
            link_verificacao = request.build_absolute_uri(
                reverse('core:verificar_email', args=[token])
            )
            send_email_verificacao(user['email'], link_verificacao)
            request.session['pending_confirm_email'] = user['email']
            return redirect('core:confirmar_email_info')
        except ValueError as e:
            messages.error(request, str(e))
            return render(request, 'core/register.html', {
                'email': email,
                'nome': nome,
                'telefone': telefone,
                'cidade': cidade,
                'estado': estado,
                'family_invite_token': family_invite_token,
            })
    
    return render(request, 'core/register.html', {
        'family_invite_token': family_invite_token,
    })


def logout_view(request):
    """View de logout."""
    request.session.flush()
    messages.success(request, 'Você saiu com sucesso.')
    return redirect('core:login')


@require_GET
def confirmar_email_info_view(request):
    """Página após cadastro: informa que um email foi enviado para confirmação."""
    email = request.session.get('pending_confirm_email', '')
    return render(request, 'core/confirmar_email_info.html', {'email': email})


def _formatar_trial_end(trial_end) -> str:
    """Formata trial_end (datetime) para dd/mm/aaaa. Ex: 14/02/2026."""
    if not trial_end or getattr(trial_end, 'strftime', None) is None:
        return ''
    return trial_end.strftime('%d/%m/%Y')


@require_GET
def verificar_email_view(request, token):
    """
    Rota: /verificar-email/<token>
    Aceita token da collection email_tokens (cadastro) ou token_confirmacao do user (reenvio).
    Só inicia trial se o email não estava confirmado antes. Passa trial_end_formatado na sessão.
    """
    from core.repositories.user_repository import UserRepository
    from core.services.trial_service import iniciar_trial
    user_repo = UserRepository()
    token_repo = EmailTokenRepository()
    if token_repo.is_valid(token, tipo='verificacao'):
        doc = token_repo.find_by_token(token)
        user_id = doc.get('user_id')
        if user_id:
            user = user_repo.find_by_id(user_id)
            email_ja_estava_verificado = bool(user and user.get('email_verificado'))
            user_repo.update(user_id, email_verificado=True)
            token_repo.mark_used(token)
            if not email_ja_estava_verificado:
                iniciar_trial(user_repo, user_id)
            user = user_repo.find_by_id(user_id)
            trial_end = (user or {}).get('trial_end') or ((user or {}).get('assinatura') or {}).get('fim')
            request.session['trial_end_formatado'] = _formatar_trial_end(trial_end)
            return redirect('core:verificar_email_sucesso')
    user = user_repo.find_by_token_confirmacao(token)
    if user:
        user_id = str(user['_id'])
        email_ja_estava_verificado = bool(user.get('email_verificado'))
        user_repo.collection.update_one(
            {'_id': user['_id']},
            {'$set': {'email_verificado': True, 'updated_at': datetime.now(timezone.utc)},
             '$unset': {'token_confirmacao': '', 'token_expira_em': ''}}
        )
        if not email_ja_estava_verificado:
            iniciar_trial(user_repo, user_id)
        user = user_repo.find_by_id(user_id)
        trial_end = (user or {}).get('trial_end') or ((user or {}).get('assinatura') or {}).get('fim')
        request.session['trial_end_formatado'] = _formatar_trial_end(trial_end)
        return redirect('core:verificar_email_sucesso')
    return render(request, 'core/link_expirado.html')


@require_GET
def verificar_email_sucesso_view(request):
    """Página de sucesso após verificar email. Exibe trial_end_formatado vindo da sessão."""
    trial_end_formatado = request.session.pop('trial_end_formatado', None) or ''
    return render(request, 'core/email_confirmado.html', {
        'trial_end_formatado': trial_end_formatado,
    })


@require_GET
def email_nao_confirmado_view(request):
    """Página exibida quando o usuário tenta login sem email confirmado. Oferece reenviar confirmação."""
    email = request.GET.get('email', '')
    return render(request, 'core/email_nao_confirmado.html', {'email': email})


@require_POST
def reenviar_confirmacao_view(request):
    """
    POST /reenviar-confirmacao
    Aceita email via form (POST) ou JSON. Se JSON, retorna JsonResponse; senão redirect.
    Valida anti-spam (60s), gera novo token, atualiza user e envia email.
    """
    from core.repositories.user_repository import UserRepository
    from urllib.parse import quote
    import json
    from django.http import JsonResponse
    wants_json = False
    email = ''
    if request.content_type and 'application/json' in request.content_type:
        wants_json = True
        try:
            body = json.loads(request.body.decode('utf-8'))
            email = (body.get('email') or '').strip().lower()
        except Exception:
            email = ''
    if not email:
        email = request.POST.get('email', '').strip().lower()
    if not email:
        if wants_json:
            return JsonResponse({'success': False, 'message': 'Informe seu email.'}, status=400)
        messages.warning(request, 'Informe seu email.')
        return redirect('core:email_nao_confirmado')
    user_repo = UserRepository()
    user = user_repo.find_by_email(email)
    if not user:
        if wants_json:
            return JsonResponse({'success': True, 'message': 'Se o email estiver cadastrado, você receberá um link.'})
        messages.success(request, 'Se o email estiver cadastrado, você receberá um link de confirmação.')
        return redirect(reverse('core:email_nao_confirmado') + '?email=' + quote(email, safe=''))
    if user.get('email_verificado', False):
        if wants_json:
            return JsonResponse({'success': False, 'message': 'Este email já está confirmado.'}, status=400)
        messages.info(request, 'Este email já está confirmado.')
        return redirect(reverse('core:email_nao_confirmado') + '?email=' + quote(email, safe=''))
    now = datetime.now(timezone.utc)
    ultimo = user.get('ultimo_envio_confirmacao')
    if ultimo:
        if getattr(ultimo, 'tzinfo', None) is None:
            ultimo = ultimo.replace(tzinfo=timezone.utc)
        if (now - ultimo).total_seconds() < 60:
            if wants_json:
                return JsonResponse({'success': False, 'message': 'Aguarde antes de reenviar.'}, status=429)
            messages.warning(request, 'Aguarde 1 minuto antes de reenviar.')
            return redirect(reverse('core:email_nao_confirmado') + '?email=' + quote(email, safe=''))
    token = str(uuid.uuid4())
    expira_em = now + timedelta(minutes=10)
    user_repo.update(str(user['_id']), token_confirmacao=token, token_expira_em=expira_em, ultimo_envio_confirmacao=now)
    link = request.build_absolute_uri(reverse('core:verificar_email', args=[token]))
    send_email_verificacao(email, link)
    if wants_json:
        return JsonResponse({'success': True, 'message': 'Email reenviado com sucesso.'})
    messages.success(request, 'Email reenviado com sucesso!')
    return redirect(reverse('core:email_nao_confirmado') + '?email=' + quote(email, safe=''))


@require_http_methods(["GET", "POST"])
def recuperar_senha_view(request):
    """
    GET: formulário com campo email.
    POST: se email existir, cria token recuperacao, envia email. Sempre mostra mensagem genérica de sucesso.
    """
    if request.method == 'GET':
        return render(request, 'core/recuperar_senha.html')
    email = request.POST.get('email', '').strip().lower()
    if not email:
        messages.error(request, 'Informe seu email.')
        return render(request, 'core/recuperar_senha.html')
    from core.repositories.user_repository import UserRepository
    user_repo = UserRepository()
    user = user_repo.find_by_email(email)
    if user:
        token = str(uuid.uuid4())
        token_repo = EmailTokenRepository()
        token_repo.create(
            user_id=str(user['_id']),
            email=email,
            token=token,
            tipo='recuperacao',
        )
        link_resetar = request.build_absolute_uri(
            reverse('core:resetar_senha', args=[token])
        )
        send_email_recuperacao(email, link_resetar)
    messages.success(
        request,
        'Se esse email estiver cadastrado, você receberá um link para redefinir sua senha em alguns minutos.'
    )
    return redirect('core:login')


@require_http_methods(["GET", "POST"])
def resetar_senha_view(request, token):
    """
    GET: formulário nova senha (token na URL).
    POST: valida token, atualiza senha, marca token usado, redireciona para login.
    """
    token_repo = EmailTokenRepository()
    doc = token_repo.find_by_token(token)
    valid = token_repo.is_valid(token, tipo='recuperacao') if doc else False
    if request.method == 'GET':
        if not valid:
            return render(request, 'core/link_expirado.html')
        return render(request, 'core/resetar_senha.html', {'token': token})
    password = request.POST.get('password', '')
    password_confirm = request.POST.get('password_confirm', '')
    if not valid or not doc:
        messages.error(request, 'Link inválido ou expirado.')
        return redirect('core:login')
    if not password or len(password) < 6:
        messages.error(request, 'A senha deve ter no mínimo 6 caracteres.')
        return render(request, 'core/resetar_senha.html', {'token': token})
    if password != password_confirm:
        messages.error(request, 'As senhas não coincidem.')
        return render(request, 'core/resetar_senha.html', {'token': token})
    user_id = doc.get('user_id')
    if not user_id:
        messages.error(request, 'Link inválido.')
        return redirect('core:login')
    import bcrypt
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    from core.repositories.user_repository import UserRepository
    user_repo = UserRepository()
    user_repo.update(user_id, password_hash=hashed)
    token_repo.mark_used(token)
    return redirect('core:senha_redefinida')


@require_GET
def senha_redefinida_view(request):
    """Página de sucesso após redefinir a senha."""
    return render(request, 'core/senha_redefinida.html')


@require_http_methods(["GET"])
def cadastro_concluido_view(request):
    """
    Página exibida após conclusão do cadastro.
    Informa sobre o trial de 7 dias e oferece botões para dashboard e WhatsApp.
    """
    from urllib.parse import quote

    telefone = request.session.get('user_telefone', '') or ''
    mensagem_whatsapp = "Olá Leozera, já concluí meu cadastro 🚀"
    if telefone:
        mensagem_whatsapp += f"\nMeu número: {telefone}"
    numero_whatsapp = "5516997874896"
    whatsapp_url = f"https://wa.me/{numero_whatsapp}?text={quote(mensagem_whatsapp)}"

    return render(request, 'core/cadastro_concluido.html', {
        'whatsapp_url': whatsapp_url,
    })


from django.http import HttpResponse
from django.conf import settings
import uuid as uuid_module


@require_http_methods(["GET", "POST"])
@login_required_mongo
def configuracoes_view(request):
    """
    Página de configurações: perfil (nome, telefone, foto), alteração de senha e alteração de email.
    Acessível apenas com usuário autenticado.
    """
    from core.repositories.user_repository import UserRepository
    import bcrypt

    user_id = request.session.get('user_id')
    if not user_id or not getattr(request, 'user_mongo', None):
        return redirect('core:login')

    user_repo = UserRepository()
    user = user_repo.find_by_id(user_id)
    if not user:
        messages.error(request, 'Usuário não encontrado.')
        return redirect('core:login')

    if request.method == 'POST':
        # Formulário de perfil (nome, telefone, foto)
        if request.POST.get('form_type') == 'perfil':
            nome = (request.POST.get('nome') or '').strip()
            telefone = (request.POST.get('telefone') or '').strip()
            updates = {}
            if nome != user.get('nome'):
                updates['nome'] = nome
            if telefone != user.get('telefone'):
                updates['telefone'] = telefone
            profile_file = request.FILES.get('profile_image')
            if profile_file:
                if profile_file.content_type and not profile_file.content_type.startswith('image/'):
                    messages.error(request, 'Envie apenas imagens (JPG, PNG, etc.).')
                else:
                    ext = os.path.splitext(profile_file.name)[1] or '.jpg'
                    safe_name = f"{uuid_module.uuid4().hex}{ext}"
                    rel_dir = os.path.join('profile_uploads', user_id)
                    media_dir = os.path.join(str(settings.MEDIA_ROOT), rel_dir)
                    os.makedirs(media_dir, exist_ok=True)
                    file_path = os.path.join(media_dir, safe_name)
                    with open(file_path, 'wb') as f:
                        for chunk in profile_file.chunks():
                            f.write(chunk)
                    rel_path = os.path.join(rel_dir, safe_name).replace('\\', '/')
                    updates['profile_image'] = rel_path
            if updates:
                user_repo.update(user_id, **updates)
                messages.success(request, 'Perfil atualizado com sucesso.')
            else:
                messages.info(request, 'Nenhuma alteração no perfil.')
            return redirect('core:configuracoes')

        # Formulário de senha
        if request.POST.get('form_type') == 'senha':
            senha_atual = request.POST.get('senha_atual', '')
            nova_senha = request.POST.get('nova_senha', '')
            confirmar_senha = request.POST.get('confirmar_senha', '')
            if not senha_atual:
                messages.error(request, 'Informe a senha atual.')
                return redirect('core:configuracoes')
            if not user_repo.verify_password_by_id(user_id, senha_atual):
                messages.error(request, 'Senha atual incorreta.')
                return redirect('core:configuracoes')
            if not nova_senha or len(nova_senha) < 6:
                messages.error(request, 'A nova senha deve ter no mínimo 6 caracteres.')
                return redirect('core:configuracoes')
            if nova_senha != confirmar_senha:
                messages.error(request, 'A confirmação da nova senha não confere.')
                return redirect('core:configuracoes')
            hashed = bcrypt.hashpw(nova_senha.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            user_repo.update(user_id, password_hash=hashed)
            messages.success(request, 'Senha alterada com sucesso.')
            return redirect('core:configuracoes')

        # Formulário de email (pending_email + token + envio)
        if request.POST.get('form_type') == 'email':
            novo_email = (request.POST.get('novo_email') or '').strip().lower()
            if not novo_email or '@' not in novo_email:
                messages.error(request, 'Informe um email válido.')
                return redirect('core:configuracoes')
            if novo_email == user.get('email'):
                messages.info(request, 'O novo email é igual ao atual.')
                return redirect('core:configuracoes')
            existing = user_repo.find_by_email(novo_email)
            if existing and str(existing.get('_id')) != user_id:
                messages.error(request, 'Este email já está em uso por outra conta.')
                return redirect('core:configuracoes')
            token = str(uuid.uuid4())
            expira_em = datetime.now(timezone.utc) + timedelta(minutes=10)
            user_repo.update(
                user_id,
                pending_email=novo_email,
                token_novo_email=token,
                token_novo_email_expira_em=expira_em,
            )
            link = request.build_absolute_uri(reverse('core:confirmar_novo_email', args=[token]))
            if send_email_novo_email(novo_email, link):
                messages.success(
                    request,
                    'Enviamos um link de confirmação para o novo email. Acesse sua caixa de entrada e clique no link para concluir a alteração.'
                )
            else:
                messages.warning(request, 'Não foi possível enviar o email. Tente novamente mais tarde.')
            return redirect('core:configuracoes')

    user = user_repo.find_by_id(user_id)
    return render(request, 'core/configuracoes.html', {
        'user': user,
        'MEDIA_URL': getattr(settings, 'MEDIA_URL', '/media/'),
    })


@require_GET
def confirmar_novo_email_view(request, token):
    """
    Rota: /confirmar-novo-email/<token>
    Confirma alteração de email: atualiza email com pending_email e limpa token.
    """
    from core.repositories.user_repository import UserRepository

    user_repo = UserRepository()
    user = user_repo.find_by_token_novo_email(token)
    if not user:
        return render(request, 'core/link_expirado.html')
    user_id = str(user['_id'])
    novo_email = user.get('pending_email')
    if not novo_email:
        return render(request, 'core/link_expirado.html')
    user_repo.collection.update_one(
        {'_id': user['_id']},
        {
            '$set': {'email': novo_email, 'updated_at': datetime.now(timezone.utc)},
            '$unset': {
                'pending_email': '',
                'token_novo_email': '',
                'token_novo_email_expira_em': '',
            }
        }
    )
    messages.success(request, 'Email atualizado com sucesso. Use o novo email para fazer login.')
    return redirect('core:configuracoes')


@require_GET
@login_required_mongo
def novidades_view(request):
    """
    Página de novidades do Leozera (changelog).
    Lista todos os updates ordenados do mais recente para o mais antigo.
    Acesso: qualquer usuário autenticado.
    """
    from core.repositories.update_repository import UpdateRepository
    repo = UpdateRepository()
    updates_raw = repo.list_all_ordered()
    # Serializar para template: _id e data_publicacao
    updates = []
    for u in updates_raw:
        updates.append({
            'id': str(u['_id']),
            'titulo': u.get('titulo', ''),
            'descricao': u.get('descricao', ''),
            'tipo': u.get('tipo', 'Atualização'),
            'data_publicacao': u.get('data_publicacao'),
        })
    return render(request, 'novidades.html', {
        'updates': updates,
        'user_mongo': getattr(request, 'user_mongo', None),
    })


@require_GET
@login_required_mongo
def observabilidade_view(request):
    from core.models.user_model import UserModel

    user_mongo = getattr(request, 'user_mongo', None)
    if not user_mongo or not UserModel.is_admin(user_mongo):
        return redirect('core:index')
    return render(request, 'observabilidade.html')


@require_GET
@login_required_mongo
def admin_observabilidade_api(request):
    """API JSON de observabilidade (métricas e logs). Apenas admin; para testes."""
    from core.models.user_model import UserModel
    from core.services.observabilidade_service import ObservabilidadeService

    if not getattr(request, 'user_mongo', None):
        return JsonResponse({"error": "unauthorized"}, status=401)

    if not UserModel.is_admin(request.user_mongo):
        return JsonResponse(
            {
                "error": "forbidden",
                "message": "Acesso restrito a administradores",
            },
            status=403,
        )

    service = ObservabilidadeService()
    metrics = service.get_metrics()
    logs = service.get_recent_logs()
    costs = service.get_costs_per_day()
    evaluations = service.get_evaluations_summary()

    return JsonResponse(
        {
            "metrics": metrics,
            "logs": logs,
            "costs": costs,
            "evaluations": evaluations,
        },
        safe=False,
    )


@require_http_methods(["GET", "POST"])
@login_required_mongo
def admin_create_update_view(request):
    """
    Criação de update (novidade). Apenas usuários com role admin.
    GET: exibe formulário. POST: salva no MongoDB e redireciona para /novidades/.
    """
    from core.repositories.update_repository import UpdateRepository, UPDATE_TIPOS
    from core.models.user_model import UserModel

    if not getattr(request, 'user_mongo', None):
        messages.error(request, 'É necessário estar logado.')
        return redirect('core:login')
    if not UserModel.is_admin(request.user_mongo):
        messages.error(request, 'Sem permissão. Apenas administradores podem publicar novidades.')
        return redirect('core:novidades')

    if request.method == 'POST':
        titulo = (request.POST.get('titulo') or '').strip()
        descricao = (request.POST.get('descricao') or '').strip()
        tipo = (request.POST.get('tipo') or '').strip()
        if not titulo:
            messages.error(request, 'O título é obrigatório.')
            return redirect('core:admin_create_update')
        if tipo not in UPDATE_TIPOS:
            tipo = 'Atualização'
        repo = UpdateRepository()
        repo.create({'titulo': titulo, 'descricao': descricao, 'tipo': tipo})
        messages.success(request, 'Novidade publicada com sucesso.')
        return redirect('core:novidades')

    return render(request, 'gerenciar/update_create.html', {'tipos': UPDATE_TIPOS})


def debug_session(request):
    before = dict(request.session)
    request.session['teste'] = 'ok'
    request.session.modified = True
    after = dict(request.session)

    return HttpResponse(
        f"ANTES: {before}\nDEPOIS: {after}\nSESSION KEY: {request.session.session_key}"
    )
