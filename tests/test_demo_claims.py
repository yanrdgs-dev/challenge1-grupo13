"""As claims da demonstração (estande) são um recorte do golden v2, sem texto próprio: nada diverge do portão."""

import json
from pathlib import Path

from src.evaluation.dataset import load_golden_dataset

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "evaluation" / "golden_demo_claims.json"
V2 = ROOT / "golden_dataset_v2.json"


def test_demo_claims_are_an_unchanged_subset_of_golden_v2():
    demo = load_golden_dataset(DEMO)
    by_id = {c["id"]: c for c in json.loads(V2.read_text(encoding="utf-8"))}
    assert demo and all(c == by_id[c["id"]] for c in demo)


def test_demo_claims_cover_the_three_verdicts_and_the_three_themes():
    demo = load_golden_dataset(DEMO)
    assert {c["expected_verdict"] for c in demo} == {"VERDADEIRO", "FALSO", "INCONCLUSIVO"}
    assert {c["category"] for c in demo} == {"GASTOS", "VOTACOES", "ELEICOES"}
    assert len({c["id"] for c in demo}) == len(demo) == 14
