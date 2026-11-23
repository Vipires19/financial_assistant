"""
Serviço de insights financeiros gerados por IA.

Localização: finance/services/ai_insights.py

Modelo híbrido: o backend calcula padrões financeiros e a IA apenas interpreta.
Gera headline, insights_chave (3 frases), diagnóstico, impacto, projeção e recomendação.
Modo "periodo": análise do intervalo filtrado. Modo "geral": foco em comportamento e hábitos (janela longa).
"""
import os
import json
import logging
from collections import defaultdict
from openai import OpenAI

logger = logging.getLogger(__name__)

# OPENAI_API_KEY deve estar no .env
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Fallback seguro quando a API falha ou a resposta não é JSON válido (novo formato)
FALLBACK_RESPONSE = {
    "headline": "",
    "insights_chave": [],
    "diagnostico": "Não foi possível gerar a análise no momento. Tente novamente mais tarde.",
    "impacto": "",
    "projecao": "",
    "recomendacao": "Verifique sua conexão e a configuração da OPENAI_API_KEY.",
}


def _calcular_taxa_economia(dados: dict) -> float:
    """Calcula taxa de economia: (total_income - total_expenses) / total_income. Retorna 0 se total_income = 0."""
    total_income = float(dados.get("total_income") or 0)
    total_expenses = float(dados.get("total_expenses") or 0)
    if total_income == 0:
        return 0.0
    return round((total_income - total_expenses) / total_income, 4)


def _calcular_percentual_categoria(dados: dict) -> tuple:
    """
    Se existir category_with_highest_expense, calcula percentual_categoria = categoria_total / total_expenses.
    Proteção: se total_expenses == 0, percentual_categoria = 0.
    Retorna (categoria_dominante, percentual_categoria) ou (None, None).
    """
    cat_info = dados.get("category_with_highest_expense")
    if not cat_info or not isinstance(cat_info, dict):
        return None, None
    total_expenses = float(dados.get("total_expenses") or 0)
    if total_expenses == 0:
        return cat_info.get("category"), 0.0
    categoria_total = float(cat_info.get("total") or 0)
    percentual = round(categoria_total / total_expenses, 4)
    return cat_info.get("category"), percentual


def _calcular_conta_mais_usada(dados: dict) -> tuple:
    """
    Agrupa despesas por account_id, identifica a conta com maior valor.
    Mapeia para nome usando accounts; se account_id não existir na lista, usa "Conta não identificada".
    Retorna (conta_mais_usada_nome, percentual_conta) ou (None, None).
    """
    transactions = dados.get("transactions") or []
    if not transactions or not isinstance(transactions, list):
        return None, None
    total_expenses = float(dados.get("total_expenses") or 0)
    if total_expenses == 0:
        return None, None

    # Agrupar gastos por account_id (apenas type expense)
    por_conta = defaultdict(float)
    for t in transactions:
        if t.get("type") != "expense":
            continue
        value = t.get("value") or 0
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        acc_id = t.get("account_id")
        key = acc_id if acc_id is not None else "__sem_conta__"
        por_conta[key] += value

    if not por_conta:
        return None, None

    conta_mais_usada_key = max(por_conta, key=por_conta.get)
    total_conta = por_conta[conta_mais_usada_key]
    # Proteção divisão por zero: se total_expenses for 0 (não deveria chegar aqui), percentual = 0
    percentual = round(total_conta / total_expenses, 4) if total_expenses else 0.0

    if conta_mais_usada_key == "__sem_conta__":
        return "Sem conta informada", percentual

    # Mapear para nome usando accounts; se não existir na lista, usar "Conta não identificada"
    conta_mais_usada = "Conta não identificada"
    accounts = dados.get("accounts") or []
    for acc in accounts:
        aid = acc.get("id") or acc.get("_id")
        if str(aid) == str(conta_mais_usada_key):
            conta_mais_usada = acc.get("name") or acc.get("nome") or "Conta não identificada"
            break
    return conta_mais_usada, percentual


def _enriquecer_dados(dados: dict) -> dict:
    """
    Enriquece o objeto dados com os padrões calculados no backend:
    taxa_economia_percent, categoria_dominante, percentual_categoria, conta_mais_usada, percentual_conta.
    Não altera o dict original; retorna uma cópia com as chaves adicionais.
    """
    enriquecido = dict(dados)

    # ALTERAÇÃO 1: Taxa de economia
    enriquecido["taxa_economia_percent"] = _calcular_taxa_economia(dados)

    # ALTERAÇÃO 2: Percentual da categoria dominante
    cat_dom, pct_cat = _calcular_percentual_categoria(dados)
    enriquecido["categoria_dominante"] = cat_dom
    enriquecido["percentual_categoria"] = pct_cat

    # ALTERAÇÃO 3: Conta mais usada
    conta, pct_conta = _calcular_conta_mais_usada(dados)
    enriquecido["conta_mais_usada"] = conta
    enriquecido["percentual_conta"] = pct_conta

    return enriquecido


def _construir_resumo_financeiro(dados_enriquecidos: dict, insight_modo: str) -> dict:
    """
    Monta objeto resumo_financeiro com apenas os campos necessários para o prompt da IA.
    No modo geral inclui ranking de categorias e sinais de hábito (dia/horário).
    """
    total_income = dados_enriquecidos.get("total_income")
    total_expenses = dados_enriquecidos.get("total_expenses")
    balance = dados_enriquecidos.get("balance")
    out = {
        "total_income": total_income if total_income is not None else 0,
        "total_expenses": total_expenses if total_expenses is not None else 0,
        "balance": balance if balance is not None else 0,
        "taxa_economia_percent": dados_enriquecidos.get("taxa_economia_percent"),
        "categoria_dominante": dados_enriquecidos.get("categoria_dominante"),
        "percentual_categoria": dados_enriquecidos.get("percentual_categoria"),
        "conta_mais_usada": dados_enriquecidos.get("conta_mais_usada"),
        "percentual_conta": dados_enriquecidos.get("percentual_conta"),
    }
    if insight_modo == "geral":
        out["contexto"] = (
            "Agregado de aproximadamente os últimos 24 meses de registros. "
            "Infira hábitos e padrões recorrentes; não trate como um único mês."
        )
        out["top_categorias_despesa"] = dados_enriquecidos.get("top_expense_categories") or []
        out["dia_com_maior_gasto"] = dados_enriquecidos.get("day_with_highest_expense")
        out["horario_com_maior_gasto"] = dados_enriquecidos.get("hour_with_highest_expense")
    return out


def _montar_prompt_periodo(resumo_json: str) -> str:
    return (
        "Você é um analista financeiro pessoal. Use os dados numéricos abaixo (já calculados) "
        "para escrever uma análise útil em português do Brasil.\n\n"
        "Responda APENAS com um único objeto JSON válido, sem markdown, neste formato exato:\n"
        "{\n"
        '  "headline": "Resumo principal em uma frase clara",\n'
        '  "insights_chave": [\n'
        '    "Insight curto 1",\n'
        '    "Insight curto 2",\n'
        '    "Insight curto 3"\n'
        "  ],\n"
        '  "diagnostico": "...",\n'
        '  "impacto": "...",\n'
        '  "projecao": "...",\n'
        '  "recomendacao": "..."\n'
        "}\n\n"
        "Instruções (modo período):\n"
        "- headline: uma frase direta sobre ONDE o dinheiro está indo ou o padrão mais importante no intervalo. "
        "Sem clichês.\n"
        "- insights_chave: exatamente 3 itens; cada um com no máximo 1 frase curta; linguagem simples; "
        "fatos baseados nos dados (categoria dominante, percentuais, conta mais usada, taxa de economia, saldo).\n"
        "- diagnostico, impacto, projecao, recomendacao: frases curtas (no máximo 2 por campo); "
        "específicos ao período analisado; evite frases genéricas vazias.\n"
        "- Não invente categorias ou valores que não apareçam nos dados; se faltar dado, seja cauteloso.\n\n"
        "Exemplo de estilo (adapte aos números reais):\n"
        '- headline: "Seus gastos estão concentrados em alimentação"\n'
        '- insights_chave: [\n'
        '    "Você gastou mais com refeições fora de casa neste período",\n'
        '    "A alimentação representa a maior parte dos seus gastos",\n'
        '    "Seus gastos estão acima da sua capacidade de economia"\n'
        "  ]\n\n"
        "Dados financeiros (JSON):\n\n"
        f"{resumo_json}"
    )


def _montar_prompt_geral(resumo_json: str) -> str:
    return (
        "Você é um analista de comportamento financeiro. Os números abaixo vêm de uma janela LONGA "
        "(cerca de 24 meses): use-os para descrever HÁBITOS e tendências, não um mês isolado.\n\n"
        "Responda APENAS com um único objeto JSON válido, sem markdown, neste formato exato:\n"
        "{\n"
        '  "headline": "Resumo do comportamento financeiro do usuário",\n'
        '  "insights_chave": [\n'
        '    "Padrão de gasto recorrente",\n'
        '    "Possível vício financeiro (hábito de consumo repetido)",\n'
        '    "Tendência de comportamento"\n'
        "  ],\n"
        '  "diagnostico": "...",\n'
        '  "impacto": "...",\n'
        '  "projecao": "...",\n'
        '  "recomendacao": "..."\n'
        "}\n\n"
        "Instruções (modo geral — comportamento e hábitos):\n"
        "- Identifique padrões ao longo do tempo: para onde o dinheiro COSTUMA ir (categorias, conta mais usada).\n"
        "- Destaque hábitos recorrentes (ex.: concentração em uma categoria, horário/dia de pico, pouca margem de economia).\n"
        "- Linguagem clara e direta. Evite termos genéricos sem conteúdo.\n"
        "- Tom: fale como COMPORTAMENTO. Prefira expressões como \"você costuma\", \"seu padrão é\", "
        "\"de forma recorrente\", \"ao longo do tempo\".\n"
        "- PROIBIDO: referir-se ao recorte como \"neste mês\", \"esse mês\", \"nesta semana\", "
        "\"hoje\", \"no período selecionado\" ou equivalentes temporais curtos.\n"
        "- \"Possível vício financeiro\" nos insights_chave significa hábito de gasto repetitivo ou automático "
        "(ex.: gasto frequente na mesma categoria), sem tom clínico ou moralizante.\n"
        "- headline: uma frase forte que responda implicitamente \"para onde meu dinheiro está indo\".\n"
        "- insights_chave: exatamente 3 frases curtas, alinhadas a: (1) padrão recorrente, "
        "(2) hábito de consumo que se repete ou pesa no orçamento, (3) tendência de comportamento "
        "(ex.: poupança consistentemente baixa).\n"
        "- diagnostico, impacto, projecao, recomendacao: no máximo 2 frases cada; "
        "projecao no estilo \"se esse padrão continuar\" (sem citar mês específico).\n"
        "- Não invente categorias ou percentuais; use top_categorias_despesa, categoria_dominante e totais fornecidos.\n\n"
        "Exemplo de estilo (adapte aos dados reais; não copie se não condizer):\n"
        '- headline: "Grande parte do seu dinheiro está indo para alimentação"\n'
        '- insights_chave: [\n'
        '    "Você tem um padrão frequente de gastos com alimentação fora de casa",\n'
        '    "Essa categoria domina seu orçamento ao longo do tempo",\n'
        '    "Sua taxa de economia permanece baixa de forma consistente"\n'
        "  ]\n\n"
        "Dados financeiros (JSON):\n\n"
        f"{resumo_json}"
    )


def _normalizar_insights_chave(val) -> list:
    """Garante lista de até 3 frases curtas (strings não vazias)."""
    if not val:
        return []
    if isinstance(val, str):
        s = val.strip()
        return [s] if s else []
    if isinstance(val, list):
        out = []
        for x in val:
            if isinstance(x, str) and x.strip():
                out.append(x.strip())
            elif x is not None and not isinstance(x, str):
                out.append(str(x).strip())
        return out[:3]
    return []


def gerar_insights_financeiros(dados: dict) -> dict:
    """
    Gera headline, insights_chave, diagnóstico, impacto, projeção e recomendação.

    O backend calcula os padrões (taxa de economia, categoria dominante, conta mais usada);
    a IA interpreta e redige em linguagem simples e direta.

    Args:
        dados: Dicionário com dados consolidados (ex.: total_income, total_expenses,
               balance, category_with_highest_expense, transactions com account_id, etc.).
               Opcional: insight_modo 'geral' ou 'periodo' (API com period=geral),
               top_expense_categories (lista com category, total, percentual_sobre_despesas).

    Returns:
        Dict com chaves: "headline", "insights_chave", "diagnostico", "impacto",
        "projecao", "recomendacao".
        Em caso de erro, retorna fallback seguro (mesmo formato).
    """
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY não configurada em ai_insights.")
        return {
            "headline": "",
            "insights_chave": [],
            "diagnostico": "Configure OPENAI_API_KEY no .env para receber análises automáticas.",
            "impacto": "",
            "projecao": "",
            "recomendacao": "Adicione OPENAI_API_KEY nas variáveis de ambiente.",
        }

    insight_modo = (dados.get("insight_modo") or "periodo").strip().lower()
    if insight_modo not in ("geral", "periodo"):
        insight_modo = "periodo"

    # Enriquece dados com padrões calculados no backend
    dados = _enriquecer_dados(dados)

    # Enviar apenas resumo_financeiro para a IA (reduz tokens e custo)
    try:
        resumo_financeiro = _construir_resumo_financeiro(dados, insight_modo)
        resumo_json = json.dumps(resumo_financeiro, ensure_ascii=False, indent=2)
    except (TypeError, ValueError) as e:
        logger.warning("Dados não serializáveis para JSON em gerar_insights_financeiros: %s", e)
        return FALLBACK_RESPONSE

    if insight_modo == "geral":
        prompt = _montar_prompt_geral(resumo_json)
    else:
        prompt = _montar_prompt_periodo(resumo_json)

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )
        content = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.exception("Erro ao chamar OpenAI em gerar_insights_financeiros: %s", e)
        return FALLBACK_RESPONSE

    # Parsing JSON robusto (ALTERAÇÃO 6: manter fallback seguro)
    try:
        if content.startswith("```"):
            parts = content.split("```")
            content = parts[1] if len(parts) > 1 else content
            if content.strip().startswith("json"):
                content = content.strip()[4:].strip()
        parsed = json.loads(content)
        headline = (parsed.get("headline") or "").strip()
        insights_chave = _normalizar_insights_chave(parsed.get("insights_chave"))
        return {
            "headline": headline,
            "insights_chave": insights_chave,
            "diagnostico": (parsed.get("diagnostico") or "").strip(),
            "impacto": (parsed.get("impacto") or "").strip(),
            "projecao": (parsed.get("projecao") or "").strip(),
            "recomendacao": (parsed.get("recomendacao") or "").strip(),
        }
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("Resposta da OpenAI não é JSON válido em gerar_insights_financeiros: %s", e)
        return FALLBACK_RESPONSE
