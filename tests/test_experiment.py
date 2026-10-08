"""Golden experiment: tarefa, avaliadores, agregação, matriz de confusão e gate (cliente mockado)."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from langfuse.experiment import ExperimentItemResult, ExperimentResult

from src.evaluation.dataset import item_id, load_golden_dataset
from src.evaluation.experiment import (
    DEFAULT_THRESHOLDS,
    RouterClient,
    check_gate,
    confusion_matrix,
    format_confusion_matrix,
    load_thresholds,
    make_evaluator,
    make_task,
    parse_threshold_args,
    run_golden_experiment,
    summarize,
)

GOLDEN = Path(__file__).resolve().parents[1] / "golden_dataset_v1.json"


def good_output(verdict="VERDADEIRO", tool="get_top_ceap_spender"):
    blocked = verdict == "INCONCLUSIVO"
    return {
        "veredito": verdict,
        "tool_usada": None if blocked else tool,
        "evidencia_coletada": None if blocked else {"ok": 1},
        "fontes_primarias": [] if blocked else ["Câmara dos Deputados - Dados Abertos (CEAP)"],
        "trace_id": "trace-x",
    }


def perfect_check(claims):
    """check_fn que acerta todas as claims do golden dataset, com a tool da categoria."""
    by_claim = {c["claim"]: c for c in claims}

    def check(claim):
        c = by_claim[claim]
        tool = "get_top_ceap_spender" if c["category"] == "GASTOS" else "get_proposition_vote_result"
        return good_output(c["expected_verdict"], tool)

    return check


class FakeLangfuse:
    """Executa task e avaliadores de verdade e devolve o ExperimentResult do SDK."""

    def __init__(self, dataset_items=None):
        self.calls = []
        self._dataset_items = dataset_items or []

    def get_dataset(self, name):
        return SimpleNamespace(items=self._dataset_items)

    def run_experiment(self, *, name, data, task, evaluators, run_name=None, max_concurrency=50, **kw):
        self.calls.append({"name": name, "run_name": run_name, "max_concurrency": max_concurrency, "n": len(data)})
        results = []
        for item in data:
            output = task(item=item)
            get = (lambda k: item[k]) if isinstance(item, dict) else (lambda k: getattr(item, k))
            evals = []
            for evaluator in evaluators:
                evals += evaluator(input=get("input"), output=output,
                                   expected_output=get("expected_output"), metadata=get("metadata"))
            results.append(ExperimentItemResult(item=item, output=output, evaluations=evals,
                                                trace_id=output.get("trace_id"), dataset_run_id=None))
        return ExperimentResult(name=name, run_name=run_name or name, description=None,
                                item_results=results, run_evaluations=[], experiment_id="exp-1")


# ------------------------------------- task ------------------------------------- #

def test_task_sends_the_claim_of_a_dict_item_to_check_fn():
    check = MagicMock(return_value={"veredito": "FALSO"})
    out = make_task(check)(item={"input": {"claim": "texto"}})
    check.assert_called_once_with("texto")
    assert out == {"veredito": "FALSO"}


def test_task_accepts_langfuse_dataset_items():
    check = MagicMock(return_value={"veredito": "FALSO"})
    make_task(check)(item=SimpleNamespace(input={"claim": "texto"}))
    check.assert_called_once_with("texto")


# --------------------------------- router client --------------------------------- #

def test_router_client_posts_claim_with_session_and_returns_json():
    resp = MagicMock()
    resp.json.return_value = {"veredito": "FALSO", "trace_id": "t"}
    with patch("httpx.Client.post", return_value=resp) as post:
        out = RouterClient("http://router:8000/", session_id="golden-1")("uma claim")
    assert out == {"veredito": "FALSO", "trace_id": "t"}
    assert post.call_args[0][0] == "http://router:8000/check"
    assert post.call_args[1]["json"] == {"claim": "uma claim", "session_id": "golden-1"}


@pytest.mark.parametrize("error", [httpx.TimeoutException("timeout"), httpx.ConnectError("sem rede")])
def test_router_client_turns_network_errors_into_an_error_output(error):
    with patch("httpx.Client.post", side_effect=error):
        out = RouterClient("http://router:8000")("claim")
    assert out["veredito"] is None
    assert out["erro"]


def test_router_client_turns_http_errors_into_an_error_output():
    resp = MagicMock()
    resp.raise_for_status.side_effect = httpx.HTTPStatusError("503", request=MagicMock(), response=MagicMock())
    with patch("httpx.Client.post", return_value=resp):
        out = RouterClient("http://router:8000")("claim")
    assert out["veredito"] is None and "503" in out["erro"]


# ---------------------------------- evaluator ---------------------------------- #

def test_evaluator_runs_scorers_with_category_from_metadata_and_skips_not_applicable():
    evals = make_evaluator()(
        input={"claim": "c"}, output=good_output("VERDADEIRO"),
        expected_output={"expected_verdict": "VERDADEIRO"}, metadata={"category": "GASTOS"},
    )
    assert {e.name: e.value for e in evals} == {
        "verdict_match": 1.0, "no_wrong_definitive": 1.0,
        "has_traceable_evidence": 1.0, "tool_category_match": 1.0,
    }  # inconclusive_without_tool não se aplica (None) e não é registrado


def test_evaluator_scores_a_failed_router_call_as_zero():
    evals = make_evaluator()(
        input={"claim": "c"}, output={"veredito": None, "erro": "timeout"},
        expected_output={"expected_verdict": "FALSO"}, metadata={"category": "GASTOS"},
    )
    by_name = {e.name: e.value for e in evals}
    assert by_name["verdict_match"] == 0.0 and by_name["has_traceable_evidence"] == 0.0


# ----------------------- confusion matrix / summarize / gate ----------------------- #

def test_confusion_matrix_counts_expected_vs_obtained_and_errors():
    pairs = [("VERDADEIRO", "VERDADEIRO"), ("VERDADEIRO", "FALSO"), ("FALSO", "FALSO"),
             ("INCONCLUSIVO", None), ("INCONCLUSIVO", "INCONCLUSIVO")]
    m = confusion_matrix(pairs)
    assert m["VERDADEIRO"]["VERDADEIRO"] == 1 and m["VERDADEIRO"]["FALSO"] == 1
    assert m["FALSO"]["FALSO"] == 1
    assert m["INCONCLUSIVO"]["ERRO"] == 1 and m["INCONCLUSIVO"]["INCONCLUSIVO"] == 1
    assert m["FALSO"]["VERDADEIRO"] == 0


def test_format_confusion_matrix_has_labels_and_counts():
    text = format_confusion_matrix(confusion_matrix([("FALSO", "FALSO"), ("FALSO", "VERDADEIRO")]))
    for label in ("VERDADEIRO", "FALSO", "INCONCLUSIVO", "ERRO", "esperado"):
        assert label in text


def test_summarize_means_matrix_and_failures():
    claims = load_golden_dataset(GOLDEN)
    items = [{"input": {"claim": c["claim"]}, "expected_output": {"expected_verdict": c["expected_verdict"]},
              "metadata": {"golden_id": c["id"], "category": c["category"]}} for c in claims]
    check = perfect_check(claims)
    wrong = claims[0]["claim"]
    def check_with_one_error(claim):
        return good_output("FALSO") if claim == wrong else check(claim)

    result = FakeLangfuse().run_experiment(name="n", data=items, task=make_task(check_with_one_error),
                                           evaluators=[make_evaluator()])
    summary = summarize(result)

    assert summary["total"] == 30
    assert summary["scores"]["verdict_match"]["mean"] == pytest.approx(29 / 30)
    assert summary["scores"]["verdict_match"]["n"] == 30
    assert summary["scores"]["inconclusive_without_tool"]["n"] == 6      # só claims INCONCLUSIVO
    assert [f["golden_id"] for f in summary["failures"]] == [1]
    assert summary["failures"][0]["expected"] == "VERDADEIRO" and summary["failures"][0]["got"] == "FALSO"
    assert summary["failures"][0]["trace_id"] == "trace-x"
    assert summary["matrix"]["VERDADEIRO"]["FALSO"] == 1


def test_check_gate_reports_each_score_below_its_threshold():
    summary = {"scores": {"verdict_match": {"mean": 0.8, "n": 30}, "has_traceable_evidence": {"mean": 1.0, "n": 30}}}
    failures = check_gate(summary, {"verdict_match": 0.9, "has_traceable_evidence": 1.0})
    assert len(failures) == 1 and "verdict_match" in failures[0]
    assert check_gate(summary, {"verdict_match": 0.8}) == []          # igual ao limiar passa


def test_check_gate_fails_when_a_thresholded_score_was_not_measured():
    failures = check_gate({"scores": {}}, {"verdict_match": 0.5})
    assert failures and "verdict_match" in failures[0]


# ---------------------------------- thresholds ---------------------------------- #

def test_default_thresholds_enforce_the_non_negotiable_rules():
    assert DEFAULT_THRESHOLDS["has_traceable_evidence"] == 1.0       # regra 1
    assert DEFAULT_THRESHOLDS["inconclusive_without_tool"] == 1.0    # regra 3


def test_load_thresholds_merges_file_over_defaults(tmp_path):
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"verdict_match": 0.7}))
    t = load_thresholds(path)
    assert t["verdict_match"] == 0.7 and t["has_traceable_evidence"] == 1.0


def test_load_thresholds_without_file_returns_defaults(tmp_path):
    assert load_thresholds(tmp_path / "nao_existe.json") == DEFAULT_THRESHOLDS


def test_parse_threshold_args():
    assert parse_threshold_args(["verdict_match=0.8", "tool_category_match=1"]) == {
        "verdict_match": 0.8, "tool_category_match": 1.0}


@pytest.mark.parametrize("bad", ["verdict_match", "verdict_match=abc", "verdict_match=1.5", "=0.5"])
def test_parse_threshold_args_rejects_invalid_values(bad):
    with pytest.raises(ValueError):
        parse_threshold_args([bad])


# ------------------------------ run_golden_experiment ------------------------------ #

def test_perfect_run_passes_the_gate_and_uses_serial_execution():
    claims = load_golden_dataset(GOLDEN)
    client = FakeLangfuse()
    summary, failures = run_golden_experiment(
        client, claims, check_fn=perfect_check(claims), run_name="baseline",
        thresholds={"verdict_match": 1.0, "has_traceable_evidence": 1.0})
    assert failures == []
    assert summary["scores"]["verdict_match"]["mean"] == 1.0
    assert client.calls[0]["max_concurrency"] == 1                    # Ollama atende uma por vez
    assert client.calls[0]["n"] == 30 and client.calls[0]["run_name"] == "baseline"


def test_degraded_run_fails_the_gate_with_readable_messages():
    claims = load_golden_dataset(GOLDEN)
    summary, failures = run_golden_experiment(
        FakeLangfuse(), claims, check_fn=lambda claim: good_output("FALSO"), run_name="ruim",
        thresholds={"verdict_match": 0.9})
    assert failures and "verdict_match" in failures[0]


def test_dataset_mode_reads_items_from_langfuse():
    claims = load_golden_dataset(GOLDEN)
    ds_items = [SimpleNamespace(id=item_id(c["id"]), input={"claim": c["claim"]},
                                expected_output={"expected_verdict": c["expected_verdict"]},
                                metadata={"golden_id": c["id"], "category": c["category"]}) for c in claims]
    client = FakeLangfuse(dataset_items=ds_items)
    summary, failures = run_golden_experiment(
        client, None, check_fn=perfect_check(claims), run_name="ds", thresholds={"verdict_match": 1.0},
        use_langfuse_dataset=True)
    assert summary["total"] == 30 and failures == []


# --------------------- limiares versionados e baseline (3.4) --------------------- #

ROOT = Path(__file__).resolve().parents[1]


def test_committed_thresholds_are_valid_and_keep_the_non_negotiable_rules():
    thresholds = load_thresholds(ROOT / "evaluation" / "thresholds.json")
    assert all(0.0 <= v <= 1.0 for v in thresholds.values())
    assert thresholds["has_traceable_evidence"] == 1.0        # regra 1
    assert thresholds["inconclusive_without_tool"] == 1.0     # regra 3
    assert thresholds["no_wrong_definitive"] == 1.0           # nunca confiantemente errado
    assert 0.0 < thresholds["verdict_match"] < 1.0            # vem do baseline


def test_committed_baseline_passes_the_committed_gate():
    baseline = json.loads((ROOT / "evaluation" / "baseline_v1.json").read_text(encoding="utf-8"))
    summary = baseline["summary"]
    assert summary["total"] == 30
    # O baseline foi medido antes do scorer no_wrong_definitive: deriva-se da matriz de confusão.
    matrix = summary["matrix"]
    wrong = sum(matrix[e][g] for e in matrix for g in ("VERDADEIRO", "FALSO") if g != e)
    assert wrong == 0
    summary["scores"]["no_wrong_definitive"] = {"mean": 1.0 if wrong == 0 else 0.0, "n": 30}
    assert check_gate(summary, load_thresholds(ROOT / "evaluation" / "thresholds.json")) == []
