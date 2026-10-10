"""Golden dataset v2 (Fase 1, passo 6): as 30 claims do v1 mais claims do TSE nos três vereditos.

Regra 5 da AGENTS.md: o v1 continua sendo o portão e não pode ser alterado; toda claim nova exige tool que a
cubra. Estes testes cuidam do arquivo e da infraestrutura de avaliação que o v2 pede (categoria ELEICOES,
INCONCLUSIVO com tool chamada e evidência vazia, nome do dataset por versão).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.evaluation.dataset import (
    DATASET_NAME,
    VALID_CATEGORIES,
    item_id,
    load_golden_dataset,
    sync_golden_dataset,
)
from src.evaluation.experiment import make_evaluator, run_golden_experiment
from src.evaluation.scorers import ALLOWED_TOOLS, inconclusive_without_tool, run_all_scorers, tool_category_match
from src.guardrails.actions import check_input_specificity
from src.services.tool_catalog import TOOLS_CATALOG

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "golden_dataset_v1.json"
V2 = ROOT / "golden_dataset_v2.json"
CATALOG = {t["function"]["name"] for t in TOOLS_CATALOG}


@pytest.fixture(scope="module")
def v2():
    return load_golden_dataset(V2)


# ------------------------------------------------------------------ o arquivo

def test_v1_claims_are_unchanged_inside_v2(v2):
    assert v2[:30] == json.loads(V1.read_text(encoding="utf-8"))


def test_v2_adds_at_least_ten_tse_claims_covering_the_three_verdicts(v2):
    tse = [c for c in v2 if c["category"] == "ELEICOES"]
    assert len(tse) >= 10
    for verdict in ("VERDADEIRO", "FALSO", "INCONCLUSIVO"):
        assert sum(c["expected_verdict"] == verdict for c in tse) >= 3, verdict


def test_v2_covers_second_round_ambiguous_candidate_and_2026(v2):
    text = " ".join(c["claim"] for c in v2 if c["category"] == "ELEICOES").lower()
    assert "segundo turno" in text
    assert "2026" in text
    ambiguous = [c for c in v2 if c.get("inconclusive_reason") == "evidencia_vazia" and "José Silva" in c["claim"]]
    assert ambiguous


def test_every_new_claim_names_tools_that_exist_in_the_router_catalog(v2):
    """Regra 5: claim nova exige cobertura de tool correspondente."""
    for claim in v2[30:]:
        assert "expected_tools" in claim, claim["id"]
        assert set(claim["expected_tools"]) <= CATALOG, claim["id"]
        if claim["expected_verdict"] != "INCONCLUSIVO":
            assert claim["expected_tools"], f"claim {claim['id']} é respondível e não tem tool"


def test_underspecified_claims_are_blocked_by_the_input_guard(v2):
    for claim in v2[30:]:
        if claim.get("inconclusive_reason") == "subespecificada":
            assert check_input_specificity(claim["claim"])["is_valid"] is False, claim["claim"]


def test_answerable_and_empty_evidence_claims_are_not_blocked_by_the_guard(v2):
    for claim in v2[30:]:
        if claim.get("inconclusive_reason") != "subespecificada":
            assert check_input_specificity(claim["claim"])["is_valid"] is True, claim["claim"]


def test_inconclusive_reason_is_validated(tmp_path):
    bad = [{"id": 1, "claim": "x", "expected_verdict": "INCONCLUSIVO", "category": "ELEICOES", "inconclusive_reason": "talvez"}]
    path = tmp_path / "g.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="inconclusive_reason"):
        load_golden_dataset(path)


def test_eleicoes_is_a_valid_category():
    assert "ELEICOES" in VALID_CATEGORIES


# ------------------------------------------------------------------ scorers

def test_tse_tools_are_allowed_for_the_eleicoes_category():
    for tool in ("get_election_result", "get_candidate_votes", "resolve_candidate", "check_candidate_status",
                 "check_disqualification_motive", "check_candidate_profile", "get_candidate_assets",
                 "check_cash_and_special_assets", "verify_official_social_media", "get_campaign_finances",
                 "get_top_campaign_finances", "check_institutional_rule"):
        assert tool in ALLOWED_TOOLS["ELEICOES"], tool
    assert tool_category_match({"tool_usada": "get_election_result"}, {"expected_verdict": "FALSO", "category": "ELEICOES"}).value == 1.0
    assert tool_category_match({"tool_usada": "get_top_ceap_spender"}, {"expected_verdict": "FALSO", "category": "ELEICOES"}).value == 0.0


EXPECTED = {"expected_verdict": "INCONCLUSIVO", "category": "ELEICOES", "inconclusive_reason": "evidencia_vazia"}
EMPTY = {"status": "resultado_indisponivel", "encontrado": False}


def test_empty_evidence_claim_accepts_a_tool_call_that_returned_no_usable_evidence():
    out = {"veredito": "INCONCLUSIVO", "tool_usada": "get_election_result", "evidencia_coletada": EMPTY}
    assert inconclusive_without_tool(out, EXPECTED).value == 1.0


def test_empty_evidence_claim_fails_if_the_tool_returned_usable_evidence():
    out = {"veredito": "INCONCLUSIVO", "tool_usada": "get_election_result", "evidencia_coletada": {"encontrado": True}}
    assert inconclusive_without_tool(out, EXPECTED).value == 0.0


def test_empty_evidence_claim_fails_if_the_verdict_is_definitive():
    out = {"veredito": "VERDADEIRO", "tool_usada": "get_election_result", "evidencia_coletada": EMPTY}
    assert inconclusive_without_tool(out, EXPECTED).value == 0.0


def test_default_inconclusive_claims_still_require_no_tool():
    out = {"veredito": "INCONCLUSIVO", "tool_usada": "get_election_result", "evidencia_coletada": EMPTY}
    assert inconclusive_without_tool(out, {"expected_verdict": "INCONCLUSIVO", "category": "ELEICOES"}).value == 0.0
    assert inconclusive_without_tool(out, {**EXPECTED, "inconclusive_reason": "subespecificada"}).value == 0.0


def test_evaluator_passes_the_reason_from_item_metadata():
    evaluator = make_evaluator()
    out = {"veredito": "INCONCLUSIVO", "tool_usada": "get_election_result", "evidencia_coletada": EMPTY}
    evals = evaluator(input={}, output=out, expected_output={"expected_verdict": "INCONCLUSIVO"},
                      metadata={"category": "ELEICOES", "inconclusive_reason": "evidencia_vazia"})
    assert {e.name: e.value for e in evals}["inconclusive_without_tool"] == 1.0
    assert run_all_scorers(out, EXPECTED)  # a função pura aceita o mesmo formato


# ------------------------------------------------------------------ nome do dataset por versão

def test_item_id_and_sync_use_the_dataset_name_given():
    client = MagicMock()
    items = [{"id": 31, "claim": "x", "expected_verdict": "FALSO", "category": "ELEICOES",
              "inconclusive_reason": None, "expected_tools": ["get_election_result"]}]
    sync_golden_dataset(client, items, dataset_name="golden_dataset_v2")
    assert client.create_dataset.call_args.kwargs["name"] == "golden_dataset_v2"
    kwargs = client.create_dataset_item.call_args.kwargs
    assert kwargs["dataset_name"] == "golden_dataset_v2" and kwargs["id"] == "golden_dataset_v2-claim-31"
    assert kwargs["metadata"]["category"] == "ELEICOES"
    assert item_id(31) == f"{DATASET_NAME}-claim-31"  # o padrão continua sendo o v1


def test_sync_keeps_the_reason_in_item_metadata():
    client = MagicMock()
    items = [{"id": 48, "claim": "x", "expected_verdict": "INCONCLUSIVO", "category": "ELEICOES",
              "inconclusive_reason": "evidencia_vazia"}]
    sync_golden_dataset(client, items, dataset_name="golden_dataset_v2")
    assert client.create_dataset_item.call_args.kwargs["metadata"]["inconclusive_reason"] == "evidencia_vazia"


def test_experiment_uses_the_dataset_name_and_forwards_the_reason():
    client = MagicMock()
    client.run_experiment.return_value = MagicMock(item_results=[], run_evaluations=[])
    claims = [{"id": 48, "claim": "x", "expected_verdict": "INCONCLUSIVO", "category": "ELEICOES",
               "inconclusive_reason": "evidencia_vazia"}]
    try:
        run_golden_experiment(client, claims, lambda c: {}, "run", {}, dataset_name="golden_dataset_v2")
    except Exception:
        pass  # só interessa o que foi passado ao Langfuse
    kwargs = client.run_experiment.call_args.kwargs
    assert kwargs["name"] == "golden_dataset_v2"
    assert kwargs["data"][0]["metadata"]["inconclusive_reason"] == "evidencia_vazia"
