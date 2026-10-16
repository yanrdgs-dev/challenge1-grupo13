"""Perguntas sobre parlamentar ("Quanto o deputado Fraga, do DF, gastou em 2022?").

Havia três falhas encadeadas: o LLM de roteamento descartava a UF da frase (homônimo "Fraga" ficava ambíguo entre
6 deputados), a tool de cota não aceitava UF para desambiguar, e uma pergunta de gasto que o LLM roteava só para
`resolve_politician` nunca chegava ao dado de gasto. A UF/cargo são completados a partir da claim (só para
desambiguar, com fallback sem UF) e a pergunta de gasto encadeia resolver → cota (regra 2).
"""

from unittest.mock import MagicMock, patch

import pytest

from src.services import router_service
from src.services.tool_args import complete_parliamentarian_args, expense_question_year

CLAIM = "Quanto o deputado Fraga, do DF, gastou em 2022?"
FRAGA = {"sq_candidato": 70001615924, "ideCadastro": 73579, "cod_senador": None, "nome_civil": "JOÃO ALBERTO FRAGA SILVA",
         "nome_urna": "Alberto Fraga", "casa": "camara", "cargo": "Deputado Federal", "uf": "DF", "partido": "PL",
         "ambiguous": False, "candidatos_alternativos": [], "match_score": 90.0}
AMBIGUOUS = {**{k: None for k in FRAGA}, "ambiguous": True, "candidatos_alternativos": [{"uf": "DF"}, {"uf": "ES"}]}
NOT_FOUND = {**{k: None for k in FRAGA}, "ambiguous": False, "candidatos_alternativos": []}


class _Result:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self):
        return self._payload


# ------------------------------------------------------------ completar UF e cargo

@pytest.mark.parametrize("tool", ["resolve_politician", "check_parliamentary_expenses"])
def test_uf_written_in_the_claim_is_added_when_the_llm_omitted_it(tool):
    args = complete_parliamentarian_args(tool, {"nome_busca": "Fraga", "ano": 2022}, CLAIM)
    assert args["uf"] == "DF"


@pytest.mark.parametrize("claim", [
    "Quanto o deputado Fraga gastou em 2022?",                      # nenhuma UF
    "Fraga, do DF, e Fulano, de MG, gastaram mais em 2022?",         # duas UFs: não se adivinha
])
def test_uf_is_not_invented_when_the_claim_has_none_or_several(claim):
    assert "uf" not in complete_parliamentarian_args("resolve_politician", {"nome_busca": "Fraga"}, claim)


def test_uf_chosen_by_the_llm_is_never_overwritten():
    args = complete_parliamentarian_args("resolve_politician", {"nome_busca": "Fraga", "uf": "ES"}, CLAIM)
    assert args["uf"] == "ES"


@pytest.mark.parametrize("claim,cargo", [
    ("Quanto o deputado Fraga, do DF, gastou em 2022?", "Deputado Federal"),
    ("Quanto a deputada federal Erika Kokay gastou em 2023?", "Deputado Federal"),
    ("Quanto o senador Fulano gastou em 2023?", "Senador"),
])
def test_cargo_is_completed_for_resolve_politician(claim, cargo):
    assert complete_parliamentarian_args("resolve_politician", {"nome_busca": "X"}, claim)["cargo"] == cargo


@pytest.mark.parametrize("claim", [
    "Quanto o deputado estadual Fulano gastou em 2022?",
    "Quanto o deputado distrital Fulano gastou em 2022?",
    "Quanto Fulano gastou em 2022?",
])
def test_cargo_is_not_completed_when_the_claim_does_not_say_it_is_a_federal_mandate(claim):
    assert "cargo" not in complete_parliamentarian_args("resolve_politician", {"nome_busca": "X"}, claim)


def test_other_tools_and_non_dict_args_are_untouched():
    args = {"cargo": "Presidente", "ano": 2022}
    assert complete_parliamentarian_args("get_election_result", args, CLAIM) == args
    assert complete_parliamentarian_args("resolve_politician", None, CLAIM) is None


def test_input_is_not_mutated():
    original = {"nome_busca": "Fraga"}
    complete_parliamentarian_args("resolve_politician", original, CLAIM)
    assert original == {"nome_busca": "Fraga"}


# ------------------------------------------------------------ pergunta de gasto

@pytest.mark.parametrize("claim,year", [
    (CLAIM, 2022),
    ("Qual foi o gasto do deputado Fraga em 2023?", 2023),
    ("Quanto de cota parlamentar o senador Fulano usou em 2021?", 2021),
    ("Fraga teve despesas de R$ 400 mil em 2023.", 2023),
])
def test_expense_question_year(claim, year):
    assert expense_question_year(claim) == year


@pytest.mark.parametrize("claim", [
    "Quanto o deputado Fraga, do DF, gastou?",                      # sem ano: não se adivinha
    "Quanto o deputado Fraga gastou entre 2022 e 2023?",            # dois anos
    "O deputado Fraga votou a favor do PL 2630/2020 em 2023?",      # não é sobre gasto
])
def test_expense_question_year_is_none_when_not_an_anchored_expense_claim(claim):
    assert expense_question_year(claim) is None


# ------------------------------------------------------------ cota: UF desambigua o nome

def test_expenses_by_name_use_the_uf_to_disambiguate():
    with patch.object(router_service, "resolve_politician", return_value=FRAGA) as resolver, \
         patch.object(router_service, "check_parliamentary_expenses", return_value=_Result({"ok": 1})) as tool:
        router_service.execute_tool(
            "check_parliamentary_expenses",
            {"casa": "camara", "ano": 2022, "parlamentar_id": "Fraga", "uf": "DF"},
        )
    assert resolver.call_args.kwargs["uf"] == "DF"
    assert tool.call_args.kwargs["parlamentar_id"] == "73579"


def test_uf_argument_is_in_the_expenses_catalog():
    from src.services.tool_catalog import TOOLS_CATALOG
    spec = next(t for t in TOOLS_CATALOG if t["function"]["name"] == "check_parliamentary_expenses")
    assert "uf" in spec["function"]["parameters"]["properties"]


# ------------------------------------------------------------ no roteador

def _route(arguments, resolver_result, tool_name="resolve_politician", claim=CLAIM, expenses=None):
    chat = MagicMock()
    chat.tool_calls = [{"name": tool_name, "arguments": arguments}]
    with patch.object(router_service, "_chat_for_routing", return_value=chat), \
         patch.object(router_service, "resolve_politician", return_value=resolver_result) as resolver, \
         patch.object(router_service, "check_parliamentary_expenses",
                      return_value=_Result(expenses or {"valor_total": 0.0, "qtd_lancamentos": 0})) as tool:
        outcome = router_service._route_and_execute(claim)
    return outcome, resolver, tool


def test_router_resolves_the_homonym_with_the_uf_from_the_claim():
    outcome, resolver, _ = _route({"nome_busca": "Fraga", "ano": 2022}, FRAGA)
    assert resolver.call_args.kwargs["uf"] == "DF"
    assert resolver.call_args.kwargs["cargo"] == "Deputado Federal"
    assert outcome.tool_args["uf"] == "DF"


def test_expense_question_routed_to_the_resolver_chains_to_the_expenses_tool_with_the_resolved_id():
    outcome, _, tool = _route({"nome_busca": "Fraga", "ano": 2022}, FRAGA, expenses={"valor_total": 123.4})
    tool.assert_called_once()
    assert tool.call_args.kwargs == {"casa": "camara", "ano": 2022, "categoria": None, "parlamentar_id": "73579"}
    assert outcome.tool_name == "check_parliamentary_expenses"
    assert outcome.tools_used == ["resolve_politician", "check_parliamentary_expenses"]
    assert outcome.evidence["valor_total"] == 123.4
    assert outcome.evidence["entidade_resolvida"]["nome_urna"] == "Alberto Fraga"
    assert outcome.evidence["entidade_resolvida"]["uf"] == "DF"


def test_senator_expense_question_uses_the_senate_code():
    senador = {**FRAGA, "ideCadastro": None, "cod_senador": 5012, "casa": "senado", "cargo": "Senador", "uf": "GO"}
    _, _, tool = _route({"nome_busca": "Fulano"}, senador, claim="Quanto o senador Fulano, de GO, gastou em 2023?")
    assert tool.call_args.kwargs["casa"] == "senado" and tool.call_args.kwargs["parlamentar_id"] == "5012"


@pytest.mark.parametrize("resolution", [AMBIGUOUS, NOT_FOUND])
def test_unresolved_entity_never_reaches_the_expenses_tool(resolution):
    outcome, _, tool = _route({"nome_busca": "Fraga", "ano": 2022}, resolution)
    tool.assert_not_called()
    assert outcome.tool_name == "resolve_politician" and outcome.tools_used == ["resolve_politician"]


@pytest.mark.parametrize("claim", [
    "Quanto o deputado Fraga, do DF, gastou?",
    "O deputado Fraga, do DF, é do PL?",
])
def test_resolver_only_claims_do_not_chain(claim):
    outcome, _, tool = _route({"nome_busca": "Fraga"}, FRAGA, claim=claim)
    tool.assert_not_called()
    assert outcome.tool_name == "resolve_politician"


def test_expenses_tool_chosen_by_the_llm_also_gets_the_uf_from_the_claim():
    outcome, resolver, tool = _route(
        {"casa": "camara", "ano": 2022, "parlamentar_id": "Fraga"}, FRAGA, tool_name="check_parliamentary_expenses"
    )
    assert resolver.call_args.kwargs["uf"] == "DF"
    assert tool.call_args.kwargs["parlamentar_id"] == "73579"
    assert outcome.tools_used == ["check_parliamentary_expenses"]
