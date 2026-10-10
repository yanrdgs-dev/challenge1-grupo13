"""Scorers determinísticos do golden experiment (funções puras, sem rede nem LLM).

Entrada: ``output`` é o JSON do ``/check`` do router e ``expected`` é uma claim do
``golden_dataset_v1.json``. Um ``Score`` com ``value=None`` significa "não se aplica" e não
deve ser registrado no Langfuse.

Mapeamento para a constituição (AGENTS.md): ``verdict_match`` (regra 5),
``no_wrong_definitive`` (regras 1 e 6), ``has_traceable_evidence`` (regra 1), ``inconclusive_without_tool`` (regra 3) e
``tool_category_match`` (regra 4).
"""

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional

from src.services.sources import evidence_failed

INCONCLUSIVE = "INCONCLUSIVO"

# Tools permitidas por categoria do golden dataset. As tools de regra institucional respondem
# "o que é permitido / como funciona" e valem nos dois temas (regra 4).
_INSTITUTIONAL = {"check_institutional_rule", "check_data_source_coverage"}
ALLOWED_TOOLS: Dict[str, FrozenSet[str]] = {
    "GASTOS": frozenset(
        {"get_top_ceap_spender", "list_expense_categories", "check_parliamentary_expenses", "resolve_politician"}
        | _INSTITUTIONAL
    ),
    "VOTACOES": frozenset(
        {"resolve_proposition", "get_proposition_vote_result", "resolve_politician"} | _INSTITUTIONAL
    ),
}


ALLOWED_TOOLS["ELEICOES"] = frozenset(
    {"resolve_candidate", "get_election_result", "get_candidate_votes", "check_candidate_status",
     "check_disqualification_motive", "check_candidate_profile", "get_candidate_assets",
     "check_cash_and_special_assets", "verify_official_social_media", "get_campaign_finances",
     "get_top_campaign_finances"} | _INSTITUTIONAL
)


@dataclass(frozen=True)
class Score:
    name: str
    value: Optional[float]
    comment: str = ""


def _verdict(output: Dict[str, Any]) -> str:
    return str(output.get("veredito") or "").strip().upper()


def _expected_verdict(expected: Dict[str, Any]) -> str:
    return str(expected.get("expected_verdict") or "").strip().upper()


def verdict_match(output: Dict[str, Any], expected: Dict[str, Any]) -> Score:
    """1.0 se o veredito final é o esperado pelo golden dataset."""
    got, want = _verdict(output), _expected_verdict(expected)
    return Score("verdict_match", 1.0 if got and got == want else 0.0, f"obtido={got or '-'} esperado={want or '-'}")


def no_wrong_definitive(output: Dict[str, Any], expected: Dict[str, Any]) -> Score:
    """Nunca emitir um veredito definitivo errado: errar para ``INCONCLUSIVO`` é aceitável, errar
    afirmando ``VERDADEIRO``/``FALSO`` diferente do esperado não é (regras 1 e 6)."""
    got, want = _verdict(output), _expected_verdict(expected)
    wrong = got in ("VERDADEIRO", "FALSO") and got != want
    return Score("no_wrong_definitive", 0.0 if wrong else 1.0, f"obtido={got or '-'} esperado={want or '-'}" if wrong else "")


def has_traceable_evidence(output: Dict[str, Any], expected: Dict[str, Any]) -> Score:
    """Veredito definitivo exige tool executada, evidência utilizável e fonte primária (regra 1)."""
    if _verdict(output) == INCONCLUSIVE:
        return Score("has_traceable_evidence", 1.0, "INCONCLUSIVO não exige evidência")

    problems = []
    if not output.get("tool_usada"):
        problems.append("nenhuma tool executada")
    if evidence_failed(output.get("evidencia_coletada")):
        problems.append("evidência ausente ou inválida")
    if not output.get("fontes_primarias"):
        problems.append("sem fonte primária")
    return Score("has_traceable_evidence", 0.0 if problems else 1.0, "; ".join(problems))


def inconclusive_without_tool(output: Dict[str, Any], expected: Dict[str, Any]) -> Score:
    """Claim subespecificada (esperado INCONCLUSIVO) deve resultar em INCONCLUSIVO sem tool (regra 3)."""
    if _expected_verdict(expected) != INCONCLUSIVE:
        return Score("inconclusive_without_tool", None, "não se aplica")

    problems = []
    if _verdict(output) != INCONCLUSIVE:
        problems.append(f"veredito {_verdict(output) or '-'} em vez de INCONCLUSIVO")
    # "evidencia_vazia": a tool pode rodar (candidato ambíguo, dado não publicado), desde que não traga evidência.
    tool_allowed = expected.get("inconclusive_reason") == "evidencia_vazia" and evidence_failed(
        output.get("evidencia_coletada")
    )
    if output.get("tool_usada") and not tool_allowed:
        problems.append(f"tool chamada: {output['tool_usada']}")
    return Score("inconclusive_without_tool", 0.0 if problems else 1.0, "; ".join(problems))


def tool_category_match(output: Dict[str, Any], expected: Dict[str, Any]) -> Score:
    """A tool chamada pertence ao conjunto permitido da categoria da claim (regra 4)."""
    if _expected_verdict(expected) == INCONCLUSIVE:
        return Score("tool_category_match", None, "não se aplica")

    tool = output.get("tool_usada")
    category = str(expected.get("category") or "").strip().upper()
    if not tool:
        return Score("tool_category_match", 0.0, "claim respondível sem nenhuma tool")
    ok = tool in ALLOWED_TOOLS.get(category, frozenset())
    return Score("tool_category_match", 1.0 if ok else 0.0, f"tool={tool} categoria={category or '-'}")


def run_all_scorers(output: Dict[str, Any], expected: Dict[str, Any]) -> List[Score]:
    """Executa os scorers determinísticos, nesta ordem."""
    return [
        verdict_match(output, expected),
        no_wrong_definitive(output, expected),
        has_traceable_evidence(output, expected),
        inconclusive_without_tool(output, expected),
        tool_category_match(output, expected),
    ]
