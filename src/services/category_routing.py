"""Roteamento em duas etapas: o LLM escolhe a categoria da alegação e depois, entre as tools dela.

Um modelo pequeno (qwen2.5:7b) erra a escolha entre ~22 tools de uma vez. Com a categoria definida ele vê
só 5 a 14 tools, e a decisão difícil (cota, proposição ou eleição) vira uma escolha entre três opções.
As tools normativas (regra 4) ficam disponíveis em toda categoria, e uma categoria inválida cai no catálogo inteiro.
"""

import logging
from typing import Any, Callable, Dict, FrozenSet, List, Optional

logger = logging.getLogger("CategoryRouting")

CLASSIFICATION_TOOL_NAME = "escolher_categoria"

# Tools de regra institucional/cobertura: valem em qualquer tema.
_NORMATIVE: FrozenSet[str] = frozenset({"check_institutional_rule", "check_data_source_coverage"})

CATEGORIES: Dict[str, Dict[str, Any]] = {
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
    "Você classifica alegações de um sistema de fact-checking político brasileiro. Escolha a categoria da "
    "alegação chamando 'escolher_categoria'. Não responda à alegação.\n"
    + "\n".join(f"- {name}: {spec['description']}" for name, spec in CATEGORIES.items())
    + "\nGasto sem menção a campanha ou eleição é COTA_PARLAMENTAR. Perguntas sobre o que é permitido ou como "
    "funciona uma regra pertencem à categoria do tema citado."
)


def classification_tool() -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": CLASSIFICATION_TOOL_NAME,
            "description": "Define a categoria da alegação.",
            "parameters": {
                "type": "object",
                "properties": {
                    "categoria": {
                        "type": "string",
                        "enum": list(CATEGORIES),
                        "description": "Categoria da alegação.",
                    },
                },
                "required": ["categoria"],
            },
        },
    }


def classify_claim(chat: Callable[..., Any], claim_text: str) -> Optional[str]:
    """Categoria da alegação, ou None se o LLM falhar ou responder algo fora do enum."""
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": claim_text},
    ]
    try:
        result = chat(messages, [classification_tool()])
    except Exception as exc:
        logger.warning("Classificação da categoria falhou (%s); usando o catálogo inteiro.", exc)
        return None
    for call in getattr(result, "tool_calls", None) or []:
        if call.get("name") == CLASSIFICATION_TOOL_NAME:
            category = (call.get("arguments") or {}).get("categoria")
            return category if category in CATEGORIES else None
    return None


def restrict_catalog(catalog: List[Dict[str, Any]], category: Optional[str]) -> List[Dict[str, Any]]:
    """Tools da categoria mais as normativas; categoria ausente ou inválida mantém o catálogo inteiro."""
    spec = CATEGORIES.get(category or "")
    if spec is None:
        return list(catalog)
    allowed = spec["tools"] | _NORMATIVE
    return [tool for tool in catalog if tool["function"]["name"] in allowed]
