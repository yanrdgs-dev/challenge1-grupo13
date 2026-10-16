"""Roteamento, fonte, scorer e juiz de check_member_vote ("Nikolas Ferreira votou contra a PEC da escala 6x1")."""

from unittest.mock import MagicMock, patch

import pytest

from src.evaluation.scorers import ALLOWED_TOOLS
from src.prompts.defaults import JUDGE_PROMPT_TEMPLATE
from src.services import router_service
from src.services.category_routing import CATEGORIES, hinted_tool, restrict_catalog
from src.services.sources import CAMARA, SENADO, derive_sources
from src.services.tool_catalog import TOOLS_CATALOG

CLAIM = "Nikolas Ferreira votou contra a PEC da escala 6x1."


# ------------------------------------------------------------ dica por redação

@pytest.mark.parametrize("claim", [
    "Nikolas Ferreira votou contra a PEC da escala 6x1.",
    "O deputado Nikolas Ferreira votou a favor da PEC 221/2019.",
    "O senador Alessandro Vieira votou contra o Marco Temporal.",
    "A deputada Erika Kokay não votou o PL 2630/2020.",
    "Como votou a senadora Damares Alves no PL 2338/2023?",
    "Qual foi o voto do deputado Kim Kataguiri na PEC da Reforma Tributária?",
])
def test_a_named_member_voting_on_a_proposition_hints_check_member_vote(claim):
    assert hinted_tool(claim) == "check_member_vote"


@pytest.mark.parametrize("claim", [
    "A Câmara votou a favor da PEC 45/2019.",
    "O Senado votou contra o PL 2630/2020.",
    "O PT votou contra a PEC da escala 6x1.",
    "O Plenário votou a PEC 221/2019 em 2026.",
    "Fulano votou em Lula no segundo turno de 2022.",
    "Quantos votos teve a PEC 45/2019 na Câmara?",
    "Os deputados votaram contra a PEC da escala 6x1.",
])
def test_institutions_parties_plurals_and_elections_do_not_hint_the_member_vote_tool(claim):
    assert hinted_tool(claim) != "check_member_vote"


def test_expense_claims_keep_their_own_hint():
    assert hinted_tool("Quanto o deputado Fraga gastou da cota parlamentar em 2023?") == "get_member_expenses"


# ------------------------------------------------------------ categoria, fonte, scorer, juiz

def test_the_tool_is_exposed_by_the_proposition_category_and_nothing_else():
    assert "check_member_vote" in CATEGORIES["PROPOSICOES"]["tools"]
    names = {t["function"]["name"] for t in restrict_catalog(TOOLS_CATALOG, "PROPOSICOES")}
    assert "check_member_vote" in names


@pytest.mark.parametrize("casa,source", [("camara", CAMARA), ("senado", SENADO)])
def test_source_follows_the_house_of_the_member(casa, source):
    assert derive_sources("check_member_vote", {}, {"casa": casa, "votos": []}) == [source]


def test_unresolved_evidence_has_no_source():
    assert derive_sources("check_member_vote", {}, {"status": "entidade_nao_resolvida", "ambiguous": False}) == []


def test_scorer_accepts_the_tool_for_votacoes():
    assert "check_member_vote" in ALLOWED_TOOLS["VOTACOES"]


def test_judge_reads_the_members_vote_and_never_treats_unregistered_as_against():
    text = JUDGE_PROMPT_TEMPLATE
    assert "check_member_vote" in text and "opcao" in text
    lowered = text.lower()
    assert "registrado" in lowered and "não é" in lowered and "contra" in lowered
    assert "turno" in lowered           # votos diferentes em turnos/destaques: a alegação precisa dizer qual


# ------------------------------------------------------------ roteador

def _chat(name, arguments):
    chat = MagicMock()
    chat.tool_calls = [{"name": name, "arguments": arguments}]
    return chat


def _route(first, retry=None, claim=CLAIM):
    side_effect = [_chat(*first)] + ([_chat(*retry)] if retry else [])
    with patch.object(router_service, "category_for", return_value="PROPOSICOES"), \
         patch.object(router_service, "_chat_for_routing", side_effect=side_effect) as chat_for_routing, \
         patch.object(router_service, "_check_member_vote", return_value={"casa": "camara", "votos": [{"opcao": "sim"}]}) as tool:
        outcome = router_service._route_and_execute(claim)
    return outcome, chat_for_routing, tool


def test_resolver_chosen_by_the_llm_is_redone_with_the_member_vote_tool_alone():
    outcome, chat_for_routing, tool = _route(
        ("resolve_proposition", {"casa": "congresso", "termo_busca": "PEC da escala 6x1"}),
        ("check_member_vote", {"parlamentar": "Nikolas Ferreira", "termo_busca": "PEC da escala 6x1"}),
    )
    assert [t["function"]["name"] for t in chat_for_routing.call_args_list[1].args[1]] == ["check_member_vote"]
    assert outcome.tool_name == "check_member_vote"
    tool.assert_called_once()
    args, claim = tool.call_args.args
    assert args["parlamentar"] == "Nikolas Ferreira" and claim == CLAIM


def test_popular_name_becomes_the_official_identification_through_the_alias_base():
    outcome, _, tool = _route(("check_member_vote", {"parlamentar": "Nikolas Ferreira", "termo_busca": "PEC da escala 6x1"}))
    args = tool.call_args.args[0]
    assert (args["sigla_tipo"], args["numero"], args["ano"]) == ("PEC", 221, 2019) and "termo_busca" not in args


def test_formally_cited_proposition_is_not_diverted_to_the_resolver():
    claim = "O deputado Nikolas Ferreira votou contra a PEC 221/2019."
    outcome, chat_for_routing, tool = _route(
        ("check_member_vote", {"parlamentar": "Nikolas Ferreira", "sigla_tipo": "PEC", "numero": 221, "ano": 2019}), claim=claim
    )
    assert chat_for_routing.call_count == 1 and outcome.tool_name == "check_member_vote"


def test_member_name_not_in_the_claim_is_discarded_without_any_lookup():
    outcome, _, tool = _route(("check_member_vote", {"parlamentar": "Arthur Lira", "termo_busca": "PEC da escala 6x1"}))
    tool.assert_not_called()
    assert outcome.evidence["status"] == "entidade_nao_resolvida" and outcome.evidence["parlamentar_informado"] == "Arthur Lira"
