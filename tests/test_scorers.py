"""Scorers determinísticos do golden experiment (funções puras)."""

import pytest

from src.evaluation.scorers import (
    Score,
    has_traceable_evidence,
    inconclusive_without_tool,
    no_wrong_definitive,
    run_all_scorers,
    tool_category_match,
    verdict_match,
)


def out(veredito="VERDADEIRO", tool="get_top_ceap_spender", evidence=None, fontes=None):
    return {
        "veredito": veredito,
        "tool_usada": tool,
        "evidencia_coletada": {"gastadores": [1]} if evidence is None else evidence,
        "fontes_primarias": ["Câmara dos Deputados - Dados Abertos (CEAP)"] if fontes is None else fontes,
    }


def exp(verdict="VERDADEIRO", category="GASTOS"):
    return {"id": 1, "claim": "c", "expected_verdict": verdict, "category": category}


# ------------------------------- verdict_match ------------------------------- #

@pytest.mark.parametrize("got, want, value", [
    ("VERDADEIRO", "VERDADEIRO", 1.0),
    ("FALSO", "FALSO", 1.0),
    ("INCONCLUSIVO", "INCONCLUSIVO", 1.0),
    ("FALSO", "VERDADEIRO", 0.0),
    ("INCONCLUSIVO", "FALSO", 0.0),
    ("verdadeiro", "VERDADEIRO", 1.0),     # normaliza caixa e espaços
    (" FALSO ", "FALSO", 1.0),
])
def test_verdict_match(got, want, value):
    score = verdict_match(out(got), exp(want))
    assert score.name == "verdict_match"
    assert score.value == value


def test_verdict_match_missing_verdict_scores_zero():
    assert verdict_match({}, exp()).value == 0.0


def test_verdict_match_comment_explains_the_mismatch():
    assert "FALSO" in verdict_match(out("FALSO"), exp("VERDADEIRO")).comment
    assert "VERDADEIRO" in verdict_match(out("FALSO"), exp("VERDADEIRO")).comment


# ---------------------------- has_traceable_evidence ---------------------------- #

def test_definitive_verdict_with_tool_evidence_and_source_passes():
    assert has_traceable_evidence(out("VERDADEIRO"), exp()).value == 1.0
    assert has_traceable_evidence(out("FALSO"), exp()).value == 1.0


@pytest.mark.parametrize("override", [
    {"tool": None},
    {"fontes": []},
    {"evidence": {"erro": "falhou"}},
    {"evidence": {"status": "entidade_nao_resolvida"}},
    {"evidence": {"encontrado": False}},
])
def test_definitive_verdict_without_traceable_evidence_fails(override):
    assert has_traceable_evidence(out("FALSO", **override), exp()).value == 0.0


def test_inconclusive_verdict_does_not_need_evidence():
    assert has_traceable_evidence(out("INCONCLUSIVO", tool=None, fontes=[]), exp("INCONCLUSIVO")).value == 1.0


# --------------------------- inconclusive_without_tool --------------------------- #

def test_underspecified_claim_must_be_inconclusive_without_tool():
    ok = inconclusive_without_tool(out("INCONCLUSIVO", tool=None, evidence={}, fontes=[]), exp("INCONCLUSIVO"))
    assert ok.value == 1.0


def test_inconclusive_with_a_tool_call_fails_the_rule():
    bad = inconclusive_without_tool(out("INCONCLUSIVO", tool="get_top_ceap_spender"), exp("INCONCLUSIVO"))
    assert bad.value == 0.0


def test_definitive_verdict_on_underspecified_claim_fails_the_rule():
    bad = inconclusive_without_tool(out("VERDADEIRO", tool=None), exp("INCONCLUSIVO"))
    assert bad.value == 0.0


@pytest.mark.parametrize("verdict", ["VERDADEIRO", "FALSO"])
def test_not_applicable_when_claim_is_answerable(verdict):
    score = inconclusive_without_tool(out(verdict), exp(verdict))
    assert score.value is None
    assert score.name == "inconclusive_without_tool"


# ----------------------------- tool_category_match ----------------------------- #

@pytest.mark.parametrize("tool, category, value", [
    ("get_top_ceap_spender", "GASTOS", 1.0),
    ("list_expense_categories", "GASTOS", 1.0),
    ("check_parliamentary_expenses", "GASTOS", 1.0),
    ("resolve_proposition", "VOTACOES", 1.0),
    ("get_proposition_vote_result", "VOTACOES", 1.0),
    ("check_institutional_rule", "GASTOS", 1.0),       # regra institucional vale nas duas
    ("check_institutional_rule", "VOTACOES", 1.0),
    ("check_data_source_coverage", "GASTOS", 1.0),
    ("get_proposition_vote_result", "GASTOS", 0.0),    # tool de votações em claim de gastos
    ("get_top_ceap_spender", "VOTACOES", 0.0),
    ("tool_inexistente", "GASTOS", 0.0),
])
def test_tool_category_match(tool, category, value):
    assert tool_category_match(out("VERDADEIRO", tool=tool), exp("VERDADEIRO", category)).value == value


def test_answerable_claim_without_any_tool_scores_zero():
    assert tool_category_match(out("FALSO", tool=None), exp("FALSO", "GASTOS")).value == 0.0


def test_not_applicable_when_inconclusive_is_expected():
    assert tool_category_match(out("INCONCLUSIVO", tool=None), exp("INCONCLUSIVO")).value is None


# -------------------------------- run_all_scorers -------------------------------- #

# ------------------------------- no_wrong_definitive ------------------------------- #

@pytest.mark.parametrize("got, want, value", [
    ("VERDADEIRO", "VERDADEIRO", 1.0),     # acertou
    ("FALSO", "FALSO", 1.0),
    ("INCONCLUSIVO", "INCONCLUSIVO", 1.0),
    ("INCONCLUSIVO", "VERDADEIRO", 1.0),   # cauteloso: errou para o lado seguro
    ("INCONCLUSIVO", "FALSO", 1.0),
    ("FALSO", "VERDADEIRO", 0.0),          # definitivo e contraditório
    ("VERDADEIRO", "FALSO", 0.0),
    ("VERDADEIRO", "INCONCLUSIVO", 0.0),   # afirmou o que devia deixar em aberto
    ("FALSO", "INCONCLUSIVO", 0.0),
])
def test_no_wrong_definitive(got, want, value):
    score = no_wrong_definitive(out(got), exp(want))
    assert score.name == "no_wrong_definitive"
    assert score.value == value


def test_missing_verdict_is_not_a_wrong_definitive():
    """Falha de infraestrutura (sem veredito) já é pontuada em verdict_match, não aqui."""
    assert no_wrong_definitive({"veredito": None, "erro": "timeout"}, exp("FALSO")).value == 1.0


def test_run_all_scorers_returns_the_deterministic_scores():
    scores = run_all_scorers(out("VERDADEIRO"), exp("VERDADEIRO"))
    assert [s.name for s in scores] == [
        "verdict_match", "no_wrong_definitive", "has_traceable_evidence",
        "inconclusive_without_tool", "tool_category_match",
    ]
    assert all(isinstance(s, Score) for s in scores)


def test_scorers_never_mutate_their_inputs():
    output, expected = out("FALSO"), exp("FALSO")
    before = (dict(output), dict(expected))
    run_all_scorers(output, expected)
    assert (output, expected) == before
