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
