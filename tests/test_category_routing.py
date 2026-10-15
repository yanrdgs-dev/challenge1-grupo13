"""Roteamento em duas etapas: primeiro a categoria da alegação, depois só as tools dessa categoria.

O modelo pequeno erra a escolha entre ~22 tools; com 4 a 12 tools da categoria certa ele acerta bem mais.
"""

from unittest.mock import MagicMock

import pytest

from src.services.category_routing import (
    CATEGORIES,
    classify_claim,
    restrict_catalog,
)
from src.services.tool_catalog import TOOLS_CATALOG

ALL_TOOLS = {t["function"]["name"] for t in TOOLS_CATALOG}


def _names(catalog):
    return {t["function"]["name"] for t in catalog}


def test_every_catalog_tool_is_reachable_from_at_least_one_category():
    """Uma tool que nenhuma categoria expõe nunca seria escolhida."""
    reachable = set().union(*(_names(restrict_catalog(TOOLS_CATALOG, c)) for c in CATEGORIES))
    assert reachable == ALL_TOOLS


def test_category_tools_exist_in_the_catalog():
    for category, spec in CATEGORIES.items():
        assert spec["tools"] <= ALL_TOOLS, category


@pytest.mark.parametrize("category, must_have, must_not_have", [
    ("COTA_PARLAMENTAR", {"get_top_ceap_spender", "get_member_expenses"}, {"get_election_result", "resolve_proposition"}),
    ("PROPOSICOES", {"resolve_proposition", "get_proposition_vote_result", "get_proposition_tramitation_history"},
     {"get_top_ceap_spender", "compare_candidates"}),
    ("ELEICOES", {"get_election_result", "resolve_candidate", "compare_candidates", "get_campaign_finances"},
     {"get_top_ceap_spender", "resolve_proposition"}),
])
def test_restricted_catalog_has_the_category_tools_and_not_the_others(category, must_have, must_not_have):
    names = _names(restrict_catalog(TOOLS_CATALOG, category))
    assert must_have <= names
    assert not (must_not_have & names)


@pytest.mark.parametrize("category", ["COTA_PARLAMENTAR", "PROPOSICOES", "ELEICOES"])
def test_normative_tools_are_available_in_every_category(category):
    """Regra 4: 'o que é permitido / como funciona' pode aparecer em qualquer tema."""
    names = _names(restrict_catalog(TOOLS_CATALOG, category))
    assert {"check_institutional_rule", "check_data_source_coverage"} <= names


def test_unknown_or_missing_category_keeps_the_full_catalog():
    assert _names(restrict_catalog(TOOLS_CATALOG, None)) == ALL_TOOLS
    assert _names(restrict_catalog(TOOLS_CATALOG, "INEXISTENTE")) == ALL_TOOLS


def test_restricting_does_not_mutate_the_catalog():
    before = list(TOOLS_CATALOG)
    restrict_catalog(TOOLS_CATALOG, "ELEICOES")
    assert TOOLS_CATALOG == before


def _chat_returning(content):
    chat = MagicMock()
    chat.return_value = MagicMock(content=content)
    return chat


def test_classify_claim_returns_the_category_chosen_by_the_llm():
    chat = _chat_returning('{"categoria": "ELEICOES"}')
    assert classify_claim(chat, "Lula teve quantos votos em 2022?") == "ELEICOES"
    messages = chat.call_args.args[0]
    assert messages[-1] == {"role": "user", "content": "Lula teve quantos votos em 2022?"}
    for name in CATEGORIES:                  # o prompt lista as categorias válidas
        assert name in messages[0]["content"]


@pytest.mark.parametrize("content", ["", "não sei", "{}", '{"categoria": "INVENTADA"}', '{"categoria": null}', "[1]"])
def test_classify_claim_returns_none_when_the_answer_is_not_a_valid_category(content):
    assert classify_claim(_chat_returning(content), "qualquer") is None


def test_classify_claim_returns_none_when_the_llm_call_fails():
    chat = MagicMock(side_effect=RuntimeError("timed out"))
    assert classify_claim(chat, "qualquer") is None


# ------------------------------ categoria por regra (sem LLM) ------------------------------ #

from src.services.category_routing import category_for, rule_category  # noqa: E402


@pytest.mark.parametrize("claim, expected", [
    ("O PL 2630/2020 foi aprovado pelo Plenário?", "PROPOSICOES"),
    ("O PLN 2/2025 trata das diretrizes orçamentárias de 2026?", "PROPOSICOES"),
    ("A PEC 45/2019 está apensada a outra proposição?", "PROPOSICOES"),
    ("Em que comissões tramitou o projeto de lei das fake news?", "PROPOSICOES"),
    ("A PEC da reforma tributária foi aprovada em primeiro turno na Câmara?", "PROPOSICOES"),
    ("Quem mais gastou a cota parlamentar da Câmara em 2023?", "COTA_PARLAMENTAR"),
    ("Senadores podem usar a CEAPS para pagar consultorias?", "COTA_PARLAMENTAR"),
    ("A verba indenizatória cobre combustível?", "COTA_PARLAMENTAR"),
    ("Quantos votos o candidato Lula teve em 2022?", "ELEICOES"),
    ("Quem mais gastou na campanha para presidente em 2022?", "ELEICOES"),
    ("O TSE indeferiu a candidatura de Fulano?", "ELEICOES"),
    ("Qual o patrimônio declarado ao TSE por Fulano?", "ELEICOES"),
])
def test_rule_category_decides_when_the_claim_has_a_clear_signal(claim, expected):
    assert rule_category(claim) == expected


@pytest.mark.parametrize("claim", [
    "Quem mais gastou em 2022?",                                   # sem sinal: o LLM decide
    "O deputado Fulano de Tal é do PL-SP.",
    "O céu é azul?",
    "A campanha da PEC 45/2019 gastou muito?",                     # sinais de duas categorias: o LLM decide
    "O candidato disse que a cota parlamentar é abusiva.",
])
def test_rule_category_is_none_when_there_is_no_signal_or_signals_conflict(claim):
    assert rule_category(claim) is None


def test_category_for_uses_the_rule_without_calling_the_llm():
    chat = MagicMock()
    assert category_for(chat, "O PL 2630/2020 foi aprovado?") == "PROPOSICOES"
    chat.assert_not_called()


def test_category_for_falls_back_to_the_llm_when_rules_do_not_decide():
    chat = _chat_returning('{"categoria": "COTA_PARLAMENTAR"}')
    assert category_for(chat, "Quem mais gastou em 2022?") == "COTA_PARLAMENTAR"
    chat.assert_called_once()


def test_category_for_is_none_when_neither_rules_nor_llm_decide():
    assert category_for(_chat_returning("{}"), "O céu é azul?") is None


@pytest.mark.parametrize("claim", [
    "Dá para ver no site do TSE quanto cada candidato declarou ter gastado na campanha eleitoral?",
    "É possível consultar publicamente quais deputados faltaram às sessões do Plenário da Câmara.",
    "Dá para consultar no Portal da Transparência quanto cada ministério gastou com diárias?",
])
def test_claims_about_what_can_be_consulted_go_to_the_normative_category_even_with_other_signals(claim):
    assert rule_category(claim) == "NORMAS"
    names = _names(restrict_catalog(TOOLS_CATALOG, "NORMAS"))
    assert names == {"check_institutional_rule", "check_data_source_coverage"}


# ------------------------------ dica de tool por regra (dentro da categoria) ------------------------------ #

from src.services.category_routing import tool_hint  # noqa: E402


@pytest.mark.parametrize("claim, tool", [
    ("Em 2022, Lula declarou ao TSE bens que somam mais de 7 milhões de reais.", "get_candidate_assets"),
    ("Jair Bolsonaro declarou um patrimônio superior a 10 milhões em 2022.", "get_candidate_assets"),
    ("Candidato declarou dinheiro em espécie e uma aeronave ao TSE.", "check_cash_and_special_assets"),
    ("Em 2022, Jair Bolsonaro venceu o segundo turno da eleição presidencial.", "get_election_result"),
    ("Quem foi o candidato mais votado para governador em 2022?", "get_election_result"),
    ("O registro de candidatura de Fulano consta como cancelado no TSE.", "check_candidate_status"),
    ("A candidatura de Fulano foi indeferida.", "check_candidate_status"),
    ("Qual a escolaridade do candidato Fulano?", "check_candidate_profile"),
])
def test_tool_hint_names_the_tool_for_clear_wording(claim, tool):
    assert tool in (tool_hint(claim) or "")


@pytest.mark.parametrize("claim", [
    "Quem mais gastou em 2022?",
    "O PL 2630/2020 foi aprovado?",
    "Lula teve 60 milhões de votos no segundo turno de 2022.",   # votos de um candidato: sem dica (o LLM decide)
])
def test_tool_hint_is_none_without_a_clear_signal(claim):
    assert tool_hint(claim) is None


def test_hinted_tool_returns_only_the_tool_name():
    from src.services.category_routing import hinted_tool

    assert hinted_tool("Em 2022, Lula declarou ao TSE bens que somam mais de 7 milhões de reais.") == "get_candidate_assets"
    assert hinted_tool("Quem mais gastou em 2022?") is None


@pytest.mark.parametrize("claim", [
    "Um partido pode receber a cota do Fundo Partidário sem prestar contas ao TSE de como gastou o dinheiro.",
    "O TSE proíbe que se divulgue publicamente o teto de gastos de campanha para presidente e governador.",
    "Os partidos precisam prestar contas do Fundo Partidário à Justiça Eleitoral?",
])
def test_rules_of_the_curated_base_go_to_normas_even_when_the_claim_mentions_the_tse(claim):
    assert rule_category(claim) == "NORMAS"


def test_campaign_money_data_claims_stay_in_eleicoes():
    assert rule_category("Quem mais gastou na campanha para presidente em 2022?") == "ELEICOES"
    assert rule_category("A campanha de Lula arrecadou mais do que a de Tebet em 2022.") == "ELEICOES"


@pytest.mark.parametrize("claim", [
    "Qual deputado registrou o menor gasto em 2022?",
    "Qual deputado teve o maior gasto com a Cota Parlamentar (CEAP) no ano de 2023?",
    "Quem foi o senador que mais gastou em 2023?",
    "O parlamentar que menos gastou em 2022 foi Fulano.",
])
def test_ranking_wording_hints_the_top_spender_tool(claim):
    assert hinted_tool(claim) == "get_top_ceap_spender"


@pytest.mark.parametrize("claim", [
    "Quanto o deputado Fraga gastou com combustível em 2023?",       # parlamentar nomeado: get_member_expenses
    "Quem mais gastou na campanha para presidente em 2022?",
])
def test_ranking_hint_does_not_fire_for_a_named_member_or_campaign(claim):
    assert hinted_tool(claim) != "get_top_ceap_spender"


def test_cota_parlamentar_used_in_campaign_goes_to_the_rules_category():
    claim = ("Deputados federais e senadores candidatos à reeleição puderam pagar o material de propaganda de suas "
             "campanhas eleitorais usando a cota parlamentar em 2022?")
    assert rule_category(claim) == "NORMAS"
    assert rule_category("Quanto o deputado Fraga gastou da cota parlamentar em 2023?") == "COTA_PARLAMENTAR"
