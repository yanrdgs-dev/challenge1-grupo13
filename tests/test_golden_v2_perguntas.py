"""Golden v2: gasto individual de parlamentar homônimo e perguntas de valor ("Quanto o deputado X gastou?").

Pergunta de valor não afirma nada a checar: o veredito é INCONCLUSIVO, mas a tool roda e traz evidência
utilizável (os números vão na justificativa). Por isso ganha a razão `pergunta_de_valor`, distinta de
`evidencia_vazia` (tool sem evidência) e de `subespecificada` (nem chama tool).
"""

from pathlib import Path

import pytest

from src.evaluation.dataset import VALID_INCONCLUSIVE_REASONS, load_golden_dataset
from src.evaluation.scorers import inconclusive_without_tool
from src.guardrails.actions import check_input_specificity

V2 = Path(__file__).resolve().parents[1] / "golden_dataset_v2.json"
QUESTION = {"expected_verdict": "INCONCLUSIVO", "category": "GASTOS", "inconclusive_reason": "pergunta_de_valor"}
USABLE = {"qtd_lancamentos": 76, "valor_total": 400218.52}


@pytest.fixture(scope="module")
def v2():
    return load_golden_dataset(V2)


def test_pergunta_de_valor_is_a_valid_reason():
    assert "pergunta_de_valor" in VALID_INCONCLUSIVE_REASONS


def test_value_question_accepts_a_tool_that_returned_usable_evidence():
    out = {"veredito": "INCONCLUSIVO", "tool_usada": "check_parliamentary_expenses", "evidencia_coletada": USABLE}
    assert inconclusive_without_tool(out, QUESTION).value == 1.0


def test_value_question_still_requires_an_inconclusive_verdict():
    out = {"veredito": "VERDADEIRO", "tool_usada": "check_parliamentary_expenses", "evidencia_coletada": USABLE}
    assert inconclusive_without_tool(out, QUESTION).value == 0.0


def test_value_question_without_any_tool_is_not_a_pass():
    """Sem tool não há valor para informar: a pergunta de valor exige a consulta."""
    out = {"veredito": "INCONCLUSIVO", "tool_usada": None, "evidencia_coletada": None}
    assert inconclusive_without_tool(out, QUESTION).value == 0.0


def test_v2_has_individual_expense_claims_for_a_homonym(v2):
    fraga = [c for c in v2 if "Fraga" in c["claim"]]
    assert len(fraga) >= 5
    verdicts = [c["expected_verdict"] for c in fraga]
    assert verdicts.count("VERDADEIRO") == verdicts.count("FALSO") >= 1  # regra 6: sem viés de verdadeiro ou falso
    reasons = {c.get("inconclusive_reason") for c in fraga}
    assert {"pergunta_de_valor", "evidencia_vazia"} <= reasons


def test_new_expense_claims_use_the_expenses_tool_and_pass_the_input_guard(v2):
    for claim in (c for c in v2 if "Fraga" in c["claim"]):
        assert claim["category"] == "GASTOS"
        assert claim["expected_tools"] == ["get_member_expenses"]
        assert check_input_specificity(claim["claim"])["is_valid"] is True


# ------------------------------------------------------------ cobertura das correções de proposição e senado

def _claim(v2, id_):
    return next(c for c in v2 if c["id"] == id_)


def test_v2_covers_the_duplicate_record_house_senator_and_descriptive_question_fixes(v2):
    new = [_claim(v2, i) for i in range(76, 81)]
    pec = [c for c in new if "PEC 45/2019" in c["claim"]]
    senadora = [c for c in new if "Damares" in c["claim"]]
    pergunta = [c for c in new if c.get("inconclusive_reason") == "pergunta_de_valor"]
    assert len(pec) == 2 and len(senadora) == 2 and len(pergunta) == 1
    for group in (pec, senadora):  # regra 6: um VERDADEIRO e um FALSO de cada
        assert sorted(c["expected_verdict"] for c in group) == ["FALSO", "VERDADEIRO"]
    assert all("na câmara" in c["claim"].lower() for c in pec)  # a Casa dita o caminho do registro duplicado
    assert all(c["expected_tools"] == ["get_member_expenses"] for c in senadora)
    assert "resolve_proposition" in pergunta[0]["expected_tools"]


def test_new_proposition_and_senator_claims_pass_the_input_guard(v2):
    for i in range(76, 81):
        assert check_input_specificity(_claim(v2, i)["claim"])["is_valid"] is True
