"""Atribuição determinística de fonte primária a partir da tool que de fato executou (regra 1).

O judge (LLM) pode citar o nome da tool, ou nenhum órgão, como "fonte". Aqui a fonte vem do
registro abaixo, que depende só da tool e da casa legislativa, e não do texto gerado.
"""

import re
from typing import Any, Dict, List, Optional

CAMARA = "Câmara dos Deputados - Dados Abertos"
SENADO = "Senado Federal - Dados Abertos"
TSE = "Tribunal Superior Eleitoral (TSE) - Dados Abertos"
CAMARA_CEAP = "Câmara dos Deputados - Dados Abertos (CEAP)"
SENADO_CEAPS = "Senado Federal - Dados Abertos (CEAPS)"

_EXPENSE_TOOLS = {"get_top_ceap_spender", "list_expense_categories", "check_parliamentary_expenses"}
_TOOL_NAME_RE = re.compile(r"^(?:get|resolve|check|list)_[a-z_]+$")


def evidence_failed(evidence: Optional[Dict[str, Any]]) -> bool:
    """True quando a tool não produziu dado utilizável (erro, ausente ou entidade não resolvida)."""
    if not evidence:
        return True
    return (
        bool(evidence.get("erro"))
        or evidence.get("status") == "entidade_nao_resolvida"
        or evidence.get("encontrado") is False
    )


def _by_casa(casa: Optional[str], camara: str, senado: str) -> List[str]:
    casa = (casa or "").strip().lower()
    if casa == "camara":
        return [camara]
    if casa == "senado":
        return [senado]
    if casa == "congresso":
        return [camara, senado]
    return []


def derive_sources(
    tool_name: Optional[str], args: Optional[Dict[str, Any]], evidence: Optional[Dict[str, Any]]
) -> List[str]:
    """Fontes primárias da tool executada. Lista vazia se não houve evidência válida."""
    if not tool_name or evidence_failed(evidence):
        return []
    args = args or {}
    casa = args.get("casa") or evidence.get("casa")

    if tool_name in _EXPENSE_TOOLS:
        return _by_casa(casa, CAMARA_CEAP, SENADO_CEAPS)
    if tool_name in ("resolve_proposition", "get_proposition_vote_result"):
        return _by_casa(casa, CAMARA, SENADO)
    if tool_name == "check_institutional_rule":
        return [evidence["fonte_normativa"]] if evidence.get("fonte_normativa") else []
    if tool_name == "check_data_source_coverage":
        return [ref for ref in (evidence.get("base_legal"), evidence.get("url_referencia")) if ref]
    if tool_name == "resolve_politician":
        sources = []
        if evidence.get("ideCadastro"):
            sources.append(CAMARA)
        if evidence.get("cod_senador"):
            sources.append(SENADO)
        if evidence.get("sq_candidato"):
            sources.append(TSE)
        return sources
    return []


def merge_sources(
    derived: List[str], judge_sources: Optional[List[Any]], tool_name: Optional[str]
) -> List[str]:
    """Fontes derivadas primeiro, depois as do judge, sem nomes de tool, vazios nem duplicatas."""
    merged: List[str] = []
    seen = set()
    for source in list(derived) + list(judge_sources or []):
        if not isinstance(source, str):
            continue
        clean = source.strip()
        key = clean.lower()
        if not clean or key in seen or key == (tool_name or "").lower() or _TOOL_NAME_RE.match(key):
            continue
        seen.add(key)
        merged.append(clean)
    return merged


def ensure_source_cited(text: str, sources: List[str]) -> str:
    """Garante que o texto cite a fonte, acrescentando-a ao final quando ainda não aparece."""
    if not sources:
        return text
    lower = (text or "").lower()
    if any(source.lower() in lower for source in sources):
        return text
    label = "Fonte" if len(sources) == 1 else "Fontes"
    return f"{text} {label}: {'; '.join(sources)}.".strip()
