"""Roteamento em duas etapas: o LLM escolhe a categoria da alegação e depois, entre as tools dela.

Um modelo pequeno (qwen2.5:7b) erra a escolha entre ~22 tools de uma vez. Com a categoria definida ele vê
só 5 a 14 tools, e a decisão difícil (cota, proposição ou eleição) vira uma escolha entre três opções.
As tools normativas (regra 4) ficam disponíveis em toda categoria, e uma categoria inválida cai no catálogo inteiro.
"""

import json
import logging
import re
import unicodedata
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger("CategoryRouting")

# Tools de regra institucional/cobertura: valem em qualquer tema.
_NORMATIVE: FrozenSet[str] = frozenset({"check_institutional_rule", "check_data_source_coverage"})

CATEGORIES: Dict[str, Dict[str, Any]] = {
    "NORMAS": {
        "description": (
            "Alegações sobre o que é PERMITIDO ou COMO FUNCIONA (regras, regimentos) ou sobre se um dado público "
            "PODE ser consultado numa fonte oficial (ex.: 'dá para ver no site do TSE...')."
        ),
        "tools": frozenset(),   # só as normativas, que toda categoria já recebe
    },
    "COTA_PARLAMENTAR": {
        "description": (
            "Gastos e reembolsos da cota parlamentar (CEAP/CEAPS) de deputados e senadores em mandato: quem mais "
            "gastou, quanto um parlamentar gastou, categorias de despesa permitidas, limites."
        ),
        "tools": frozenset({
            "get_top_ceap_spender", "list_expense_categories", "check_parliamentary_expenses",
            "get_member_expenses", "resolve_politician",
        }),
    },
    "PROPOSICOES": {
        "description": (
            "Projetos e propostas do Congresso (PL, PLP, PLN, PEC, MPV, PDL) e nomes populares de matérias: "
            "identificar a proposição, votações e resultado em plenário, tramitação, comissões, apensamento."
        ),
        "tools": frozenset({
            "resolve_proposition", "get_proposition_vote_result", "get_proposition_tramitation_history",
            "check_bill_apensamentos", "resolve_politician",
        }),
    },
    "ELEICOES": {
        "description": (
            "Eleições e candidatos (TSE): resultado e votos, candidatura deferida ou indeferida, patrimônio "
            "declarado, redes sociais oficiais, gastos e arrecadação de CAMPANHA, comparação entre candidatos."
        ),
        "tools": frozenset({
            "resolve_candidate", "get_election_result", "get_candidate_votes", "check_candidate_status",
            "check_disqualification_motive", "check_candidate_profile", "get_candidate_assets",
            "check_cash_and_special_assets", "verify_official_social_media", "get_campaign_finances",
            "get_top_campaign_finances", "compare_candidates",
        }),
    },
}

_SYSTEM_PROMPT = (
    "Você classifica alegações de um sistema de fact-checking político brasileiro. Responda SOMENTE um JSON "
    '{"categoria": "<NOME>"} com um dos nomes abaixo. Não responda à alegação.\n'
    + "\n".join(f"- {name}: {spec['description']}" for name, spec in CATEGORIES.items())
    + "\nGasto sem menção a campanha ou eleição é COTA_PARLAMENTAR. Perguntas sobre o que é permitido ou como "
    "funciona uma regra pertencem à categoria do tema citado."
)


def classify_claim(chat: Callable[..., Any], claim_text: str) -> Optional[str]:
    """Categoria da alegação, ou None se o LLM falhar ou responder algo fora das categorias.

    ``chat(messages)`` deve devolver um objeto com ``content`` em JSON (modo JSON do provedor): o modelo
    pequeno não chama de forma confiável uma função de uma única opção, mas responde JSON direito.
    """
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": claim_text},
    ]
    try:
        content = getattr(chat(messages), "content", "") or ""
        category = json.loads(content).get("categoria")
    except Exception as exc:
        logger.warning("Classificação da categoria falhou (%s); usando o catálogo inteiro.", exc)
        return None
    return category if category in CATEGORIES else None


def restrict_catalog(catalog: List[Dict[str, Any]], category: Optional[str]) -> List[Dict[str, Any]]:
    """Tools da categoria mais as normativas; categoria ausente ou inválida mantém o catálogo inteiro."""
    spec = CATEGORIES.get(category or "")
    if spec is None:
        return list(catalog)
    allowed = spec["tools"] | _NORMATIVE
    return [tool for tool in catalog if tool["function"]["name"] in allowed]


# Sinais inequívocos de cada tema. Dois temas no mesmo texto, ou nenhum, deixam a decisão para o LLM.
_SIGNALS: Dict[str, "re.Pattern[str]"] = {
    "PROPOSICOES": re.compile(
        r"\b(?:plp|pln|plv|pl|pec|mpv|pdl|pdc)\s*n?[o.]?\s*\d|\b(?:pec|plp|pln|mpv|pdl)\b|"
        r"projeto de lei|proposta de emenda|medida provisoria|tramit|apens",
    ),
    "COTA_PARLAMENTAR": re.compile(
        r"cota parlamentar|\bceaps?\b|verba indenizatoria|cota para o exercicio|cota de passagens|reembols",
    ),
    "ELEICOES": re.compile(
        r"campanh|eleic|eleit|candidat|\btse\b|prestacao de contas|patrimonio declarado|fundo eleitoral|"
        r"fundo partidario|ficha limpa|inelegi",
    ),
}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# "Dá para ver / é possível consultar ..." pergunta se o dado existe numa fonte oficial: vale mesmo que a
# alegação cite eleição ou parlamentares, porque a resposta é sobre a fonte, não sobre o dado.
_CONSULT_RE = re.compile(
    r"\bda para (?:ver|consultar|acessar|baixar)|e possivel (?:consultar|ver|acessar|baixar)|"
    r"pode(?:m)? ser consultad|consult(?:a|ar|ado) publicamente",
)


# Temas que a base normativa curada responde por escrito (lei, regimento, resolução), mesmo quando a alegação
# cita o TSE ou a cota: a pergunta é sobre a regra, não sobre os dados.
_RULES_RE = re.compile(
    r"fundo partidario|fundo eleitoral|prestar contas|teto de gastos|"
    r"cota parlamentar.{0,200}(?:campanh|propaganda)|(?:campanh|propaganda).{0,200}cota parlamentar"
)


def rule_category(claim_text: str) -> Optional[str]:
    """Categoria decidida só por regra: exatamente um tema com sinal claro na alegação, senão None."""
    folded = _fold(claim_text)
    if _CONSULT_RE.search(folded) or _RULES_RE.search(folded):
        return "NORMAS"
    hits = [name for name, pattern in _SIGNALS.items() if pattern.search(folded)]
    return hits[0] if len(hits) == 1 else None


def category_for(chat: Callable[..., Any], claim_text: str) -> Optional[str]:
    """Regra primeiro (sem custo de LLM); o LLM só classifica quando a regra não decide."""
    return rule_category(claim_text) or classify_claim(chat, claim_text)


# Dentro de ELEICOES o modelo pequeno confunde tools vizinhas (patrimônio x dinheiro em espécie x perfil, vencedor
# x votos de um candidato). Quando a redação é inequívoca, a regra nomeia a tool no prompt do roteamento; o LLM
# continua extraindo os parâmetros. Ordem importa: o primeiro padrão que casa vence.
_TOOL_HINTS: List[Tuple["re.Pattern[str]", str, str]] = [
    (re.compile(r"(?:qual|quais|quem)\b[^?.]{0,50}\b(?:deputad\w*|senador\w*|parlamentar\w*)\b[^?.]{0,60}\b(?:maior|menor|mais|menos)\b[^?.]{0,30}\bgast|"
                r"(?:deputad\w*|senador\w*|parlamentar\w*) que (?:mais|menos) gast"),
     "get_top_ceap_spender", "ranking de gastos da cota parlamentar (quem mais ou menos gastou)"),
    (re.compile(r"dinheiro em especie|aeronave|aviao|embarcacao|joias?\b|\bouro\b|bens especiais"),
     "check_cash_and_special_assets", "dinheiro em espécie ou bens especiais (aeronave, embarcação, joias)"),
    (re.compile(r"patrimonio|bens (?:declarad|que somam)|declarou .{0,40}\bbens\b|declarou .{0,40}reais? em bens"),
     "get_candidate_assets", "patrimônio ou bens declarados por um candidato"),
    (re.compile(r"\b(?:venceu|ganhou|vencedor|vencedora|mais votad[oa]|ficou em segundo|foi o eleito)\b"),
     "get_election_result", "quem venceu ou foi o mais votado de uma eleição"),
    (re.compile(r"candidatura|registro de candidat|indeferid|deferid|cancelad|renunci"),
     "check_candidate_status", "situação do registro de candidatura"),
    (re.compile(r"escolaridade|grau de instrucao|profissao|ocupacao|naturalidade|estado civil|cor/raca"),
     "check_candidate_profile", "perfil do candidato (escolaridade, profissão, naturalidade)"),
]


_CAMPAIGN_WORDS_RE = re.compile(r"campanh|eleic|candidat")


def _matching_hint(claim_text: str) -> Optional[Tuple[str, str]]:
    folded = _fold(claim_text)
    for pattern, tool, topic in _TOOL_HINTS:
        if pattern.search(folded):
            if tool == "get_top_ceap_spender" and _CAMPAIGN_WORDS_RE.search(folded):
                continue   # "quem mais gastou na campanha" é dado do TSE, não da cota
            return tool, topic
    return None


def hinted_tool(claim_text: str) -> Optional[str]:
    """Nome da tool que a redação aponta; None se não há sinal claro."""
    hint = _matching_hint(claim_text)
    return hint[0] if hint else None


def tool_hint(claim_text: str) -> Optional[str]:
    """Dica de roteamento (texto para o prompt) quando a redação aponta uma tool só; None se não há sinal claro."""
    hint = _matching_hint(claim_text)
    return f"\n\nDica de roteamento: a alegação trata de {hint[1]}; utilize '{hint[0]}'." if hint else None
