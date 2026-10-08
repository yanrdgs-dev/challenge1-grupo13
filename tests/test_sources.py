"""Atribuição determinística de fonte primária a partir da tool executada (regra 1)."""

import pytest

from src.services.sources import derive_sources, ensure_source_cited, merge_sources

CAMARA_CEAP = "Câmara dos Deputados - Dados Abertos (CEAP)"
SENADO_CEAPS = "Senado Federal - Dados Abertos (CEAPS)"
CAMARA = "Câmara dos Deputados - Dados Abertos"
SENADO = "Senado Federal - Dados Abertos"
TSE = "Tribunal Superior Eleitoral (TSE) - Dados Abertos"


# ------------------------------ derive_sources ------------------------------ #

@pytest.mark.parametrize("tool", ["get_top_ceap_spender", "list_expense_categories", "check_parliamentary_expenses"])
@pytest.mark.parametrize("casa, expected", [("camara", CAMARA_CEAP), ("senado", SENADO_CEAPS)])
def test_expense_tools_cite_ceap_source_by_casa(tool, casa, expected):
    assert derive_sources(tool, {"casa": casa, "ano": 2023}, {"total": 1}) == [expected]


def test_casa_falls_back_to_evidence_when_missing_from_args():
    assert derive_sources("get_top_ceap_spender", {}, {"casa": "senado"}) == [SENADO_CEAPS]


@pytest.mark.parametrize("casa, expected", [("camara", [CAMARA]), ("senado", [SENADO]), ("congresso", [CAMARA, SENADO])])
def test_resolve_proposition_cites_house_source(casa, expected):
    assert derive_sources("resolve_proposition", {"casa": casa}, {"id": 1}) == expected


@pytest.mark.parametrize("casa, expected", [("camara", [CAMARA]), ("senado", [SENADO])])
def test_vote_result_cites_house_source(casa, expected):
    assert derive_sources("get_proposition_vote_result", {"casa": casa}, {"votacoes": []}) == expected


def test_resolve_politician_sources_follow_the_identifiers_found():
    evidence = {"ideCadastro": 7, "cod_senador": None, "sq_candidato": 99}
    assert derive_sources("resolve_politician", {}, evidence) == [CAMARA, TSE]
    assert derive_sources("resolve_politician", {}, {"cod_senador": 5}) == [SENADO]


@pytest.mark.parametrize("evidence", [
    None,
    {},
    {"erro": "duckdb falhou"},
    {"status": "entidade_nao_resolvida", "ambiguous": False},
])
def test_failed_or_empty_evidence_means_no_source_for_any_tool(evidence):
    for tool in ("get_top_ceap_spender", "resolve_proposition", "get_proposition_vote_result", "resolve_politician"):
        assert derive_sources(tool, {"casa": "camara"}, evidence) == [], tool


def test_resolve_politician_without_any_identifier_has_no_source():
    evidence = {"ideCadastro": None, "cod_senador": None, "sq_candidato": None, "ambiguous": False}
    assert derive_sources("resolve_politician", {}, evidence) == []


def test_unknown_tool_has_no_source():
    assert derive_sources("tool_inexistente", {"casa": "camara"}, {"a": 1}) == []


# ------------------------------- merge_sources ------------------------------- #

def test_merge_puts_derived_sources_first():
    assert merge_sources([CAMARA_CEAP], ["TSE"], "get_top_ceap_spender") == [CAMARA_CEAP, "TSE"]


def test_merge_drops_tool_names_cited_as_source():
    merged = merge_sources([CAMARA_CEAP], ["get_top_ceap_spender", "resolve_politician"], "get_top_ceap_spender")
    assert merged == [CAMARA_CEAP]


def test_merge_dedupes_case_insensitively_and_ignores_blanks():
    merged = merge_sources([CAMARA_CEAP], [CAMARA_CEAP.upper(), "  ", "", None], "x")
    assert merged == [CAMARA_CEAP]


def test_merge_keeps_judge_sources_when_nothing_was_derived():
    assert merge_sources([], ["Câmara dos Deputados"], "x") == ["Câmara dos Deputados"]


# ----------------------------- ensure_source_cited ----------------------------- #

def test_ensure_source_cited_appends_when_missing():
    text = ensure_source_cited("A evidência confirma o fato.", [CAMARA_CEAP])
    assert text == f"A evidência confirma o fato. Fonte: {CAMARA_CEAP}."


def test_ensure_source_cited_lists_multiple_sources():
    text = ensure_source_cited("Confirmado.", [CAMARA, TSE])
    assert text == f"Confirmado. Fontes: {CAMARA}; {TSE}."


def test_ensure_source_cited_does_not_repeat_when_already_cited():
    original = "Segundo a Câmara dos Deputados - Dados Abertos (CEAP), confirmado."
    assert ensure_source_cited(original, [CAMARA_CEAP]) == original


def test_ensure_source_cited_without_sources_keeps_text():
    assert ensure_source_cited("Sem fonte.", []) == "Sem fonte."


# ----------------------- tools normativas (base curada) ----------------------- #

def test_institutional_rule_cites_its_normative_source():
    evidence = {"encontrado": True, "fonte_normativa": "Constituição Federal, art. 52, III"}
    assert derive_sources("check_institutional_rule", {"topico": "sabatina_stf"}, evidence) == [
        "Constituição Federal, art. 52, III"
    ]


def test_data_source_coverage_cites_legal_basis_and_reference():
    evidence = {"encontrado": True, "base_legal": "Lei 9.504/1997", "url_referencia": "https://divulgacandcontas.tse.jus.br"}
    assert derive_sources("check_data_source_coverage", {}, evidence) == [
        "Lei 9.504/1997",
        "https://divulgacandcontas.tse.jus.br",
    ]


def test_data_source_coverage_without_url_cites_only_legal_basis():
    evidence = {"encontrado": True, "base_legal": "Lei 12.527/2011 (LAI)", "url_referencia": None}
    assert derive_sources("check_data_source_coverage", {}, evidence) == ["Lei 12.527/2011 (LAI)"]


@pytest.mark.parametrize("tool", ["check_institutional_rule", "check_data_source_coverage"])
def test_not_found_in_curated_base_means_no_source(tool):
    evidence = {"encontrado": False, "fonte_normativa": None, "base_legal": None, "mensagem": "não catalogado"}
    assert derive_sources(tool, {}, evidence) == []
