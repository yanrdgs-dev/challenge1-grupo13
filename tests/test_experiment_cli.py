"""CLI do golden experiment: saída legível e código de saída usado como gate no CI."""

import json
from pathlib import Path

import pytest

from scripts.run_golden_experiment import main
from src.evaluation.dataset import load_golden_dataset
from tests.test_experiment import FakeLangfuse, perfect_check

GOLDEN = Path(__file__).resolve().parents[1] / "golden_dataset_v1.json"


@pytest.fixture
def claims():
    return load_golden_dataset(GOLDEN)


def run(argv, claims, check=None, client=None, tmp_path=None):
    client = client or FakeLangfuse()
    check_fn = check or perfect_check(claims)
    return main(
        ["--golden-path", str(GOLDEN)] + argv + (["--thresholds-file", str(tmp_path / "nenhum.json")] if tmp_path else []),
        client_factory=lambda: client,
        check_fn_factory=lambda url, session: check_fn,
    ), client


def test_perfect_run_exits_zero_and_prints_matrix_scores_and_gate(claims, capsys, tmp_path):
    code, client = run(["--local", "--run-name", "baseline", "--threshold", "verdict_match=1"], claims, tmp_path=tmp_path)
    out = capsys.readouterr().out
    assert code == 0
    assert "esperado \\ obtido" in out
    assert "verdict_match" in out and "100.0%" in out
    assert "GATE APROVADO" in out
    assert client.calls[0]["run_name"] == "baseline"


def test_gate_failure_exits_one_and_lists_wrong_claims(claims, capsys, tmp_path):
    code, _ = run(["--local", "--threshold", "verdict_match=1"], claims,
                  check=lambda claim: {"veredito": "FALSO", "tool_usada": "get_top_ceap_spender",
                                       "evidencia_coletada": {"a": 1}, "fontes_primarias": ["x"], "trace_id": "t-1"},
                  tmp_path=tmp_path)
    out = capsys.readouterr().out
    assert code == 1
    assert "GATE REPROVADO" in out
    assert "verdict_match" in out
    assert "t-1" in out                                  # trace para inspecionar a claim errada


def test_default_gate_enforces_constitution_rules_even_without_flags(claims, capsys, tmp_path):
    """Sem nenhum --threshold, a regra 1 (evidência rastreável) ainda reprova."""
    code, _ = run(["--local"], claims,
                  check=lambda claim: {"veredito": "VERDADEIRO", "tool_usada": None,
                                       "evidencia_coletada": None, "fontes_primarias": []},
                  tmp_path=tmp_path)
    assert code == 1
    assert "has_traceable_evidence" in capsys.readouterr().out


def test_thresholds_file_is_applied(claims, tmp_path):
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"verdict_match": 1.0}))
    code = main(["--local", "--golden-path", str(GOLDEN), "--thresholds-file", str(path)], client_factory=lambda: FakeLangfuse(),
                   check_fn_factory=lambda u, s: (lambda claim: {"veredito": "FALSO", "tool_usada": "get_top_ceap_spender",
                                                                  "evidencia_coletada": {"a": 1}, "fontes_primarias": ["x"]}))
    assert code == 1


def test_invalid_threshold_returns_usage_error(claims, capsys, tmp_path):
    code, _ = run(["--local", "--threshold", "verdict_match=2"], claims, tmp_path=tmp_path)
    assert code == 2
    assert "Limiar inválido" in capsys.readouterr().err


def test_json_output_option_writes_the_summary(claims, tmp_path):
    target = tmp_path / "resumo.json"
    run(["--local", "--json-out", str(target)], claims, tmp_path=tmp_path)
    data = json.loads(target.read_text())
    assert data["total"] == 30 and "matrix" in data and "scores" in data


def test_router_url_and_session_are_passed_to_the_check_factory(claims, tmp_path):
    seen = {}

    def factory(url, session):
        seen["url"], seen["session"] = url, session
        return perfect_check(claims)

    main(["--local", "--golden-path", str(GOLDEN), "--router-url", "http://router:8000", "--run-name", "r1",
          "--thresholds-file", str(tmp_path / "x.json")],
         client_factory=lambda: FakeLangfuse(), check_fn_factory=factory)
    assert seen == {"url": "http://router:8000", "session": "golden-r1"}
