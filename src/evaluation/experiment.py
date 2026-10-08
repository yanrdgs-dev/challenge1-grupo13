"""Golden experiment: roda as claims no router, pontua com os scorers e aplica o gate de limiares."""

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import httpx
from langfuse.experiment import Evaluation

from src.evaluation.dataset import DATASET_NAME, VALID_VERDICTS
from src.evaluation.scorers import run_all_scorers

ERROR_COLUMN = "ERRO"

# Regras inegociáveis da constituição: 1 (evidência rastreável) e 3 (subespecificada ⇒ INCONCLUSIVO
# sem tool) não admitem exceção. Os demais limiares saem do baseline (tarefa 3.4).
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "has_traceable_evidence": 1.0,
    "inconclusive_without_tool": 1.0,
}


def _field(item: Any, key: str) -> Any:
    """Campo de um item do experimento (dict local ou DatasetItem do Langfuse)."""
    return item.get(key) if isinstance(item, dict) else getattr(item, key, None)


# --------------------------------- task e cliente --------------------------------- #

def make_task(check_fn: Callable[[str], Dict[str, Any]]) -> Callable[..., Dict[str, Any]]:
    def task(*, item: Any, **kwargs: Any) -> Dict[str, Any]:
        return check_fn(_field(item, "input")["claim"])

    return task


class RouterClient:
    """Chama o ``/check`` do router. Falhas viram um output de erro (pontuado como 0), sem levantar."""

    def __init__(self, base_url: str, session_id: Optional[str] = None, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id
        self.timeout = timeout

    def __call__(self, claim: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"claim": claim}
        if self.session_id:
            body["session_id"] = self.session_id
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self.base_url}/check", json=body)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            return {"veredito": None, "erro": f"{type(exc).__name__}: {exc}"}


def make_evaluator() -> Callable[..., List[Evaluation]]:
    def evaluator(*, input: Any, output: Any, expected_output: Any, metadata: Any, **kwargs: Any) -> List[Evaluation]:
        expected = {**(expected_output or {}), "category": (metadata or {}).get("category")}
        return [
            Evaluation(name=s.name, value=s.value, comment=s.comment or None)
            for s in run_all_scorers(output or {}, expected)
            if s.value is not None
        ]

    return evaluator


# ------------------------------ matriz de confusão ------------------------------ #

def confusion_matrix(pairs: List[Tuple[str, Optional[str]]]) -> Dict[str, Dict[str, int]]:
    """Linhas = veredito esperado; colunas = obtido (ou ``ERRO`` quando não houve veredito válido)."""
    columns = list(VALID_VERDICTS) + [ERROR_COLUMN]
    matrix = {row: {col: 0 for col in columns} for row in VALID_VERDICTS}
    for expected, got in pairs:
        column = got if got in VALID_VERDICTS else ERROR_COLUMN
        matrix[expected][column] += 1
    return matrix


def format_confusion_matrix(matrix: Dict[str, Dict[str, int]]) -> str:
    columns = list(VALID_VERDICTS) + [ERROR_COLUMN]
    width = 14
    header = "esperado \\ obtido".ljust(width + 4) + "".join(c.rjust(width) for c in columns)
    lines = [header]
    for row in VALID_VERDICTS:
        lines.append(row.ljust(width + 4) + "".join(str(matrix[row][c]).rjust(width) for c in columns))
    return "\n".join(lines)


# ----------------------------- agregação e gate ----------------------------- #

def summarize(result: Any) -> Dict[str, Any]:
    """Resumo do ``ExperimentResult``: média por score, matriz de confusão e claims erradas."""
    values: Dict[str, List[float]] = {}
    pairs: List[Tuple[str, Optional[str]]] = []
    failures: List[Dict[str, Any]] = []

    for item_result in result.item_results:
        expected = (_field(item_result.item, "expected_output") or {}).get("expected_verdict")
        metadata = _field(item_result.item, "metadata") or {}
        output = item_result.output or {}
        got = output.get("veredito")
        pairs.append((expected, got))

        for evaluation in item_result.evaluations:
            values.setdefault(evaluation.name, []).append(float(evaluation.value))

        if got != expected:
            failures.append({
                "golden_id": metadata.get("golden_id"),
                "expected": expected,
                "got": got,
                "trace_id": output.get("trace_id") or item_result.trace_id,
                "erro": output.get("erro"),
            })

    return {
        "run_name": getattr(result, "run_name", None),
        "dataset_run_url": getattr(result, "dataset_run_url", None),
        "total": len(result.item_results),
        "scores": {name: {"mean": sum(v) / len(v), "n": len(v)} for name, v in values.items()},
        "matrix": confusion_matrix(pairs),
        "failures": failures,
    }


def check_gate(summary: Dict[str, Any], thresholds: Dict[str, float]) -> List[str]:
    """Mensagens de cada score abaixo do limiar (lista vazia = gate aprovado)."""
    problems = []
    for name, minimum in thresholds.items():
        measured = summary["scores"].get(name)
        if measured is None:
            problems.append(f"{name}: não medido (limiar {minimum:.0%})")
        elif measured["mean"] + 1e-9 < minimum:
            problems.append(f"{name}: {measured['mean']:.1%} abaixo do limiar {minimum:.0%}")
    return problems


def load_thresholds(path: Union[str, Path]) -> Dict[str, float]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    path = Path(path)
    if path.exists():
        thresholds.update({k: float(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()})
    return thresholds


def parse_threshold_args(args: List[str]) -> Dict[str, float]:
    """Converte ``["verdict_match=0.8"]`` em ``{"verdict_match": 0.8}``."""
    parsed: Dict[str, float] = {}
    for arg in args:
        name, sep, raw = arg.partition("=")
        if not sep or not name.strip():
            raise ValueError(f"Limiar inválido '{arg}': use nome=valor.")
        try:
            value = float(raw)
        except ValueError:
            raise ValueError(f"Limiar inválido '{arg}': valor não numérico.") from None
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"Limiar inválido '{arg}': o valor deve estar entre 0 e 1.")
        parsed[name.strip()] = value
    return parsed


# --------------------------------- orquestração --------------------------------- #

def run_golden_experiment(
    client: Any,
    claims: Optional[List[Dict[str, Any]]],
    check_fn: Callable[[str], Dict[str, Any]],
    run_name: str,
    thresholds: Dict[str, float],
    use_langfuse_dataset: bool = False,
) -> Tuple[Dict[str, Any], List[str]]:
    """Roda o experimento (um item por vez: o Ollama atende uma request por vez) e aplica o gate."""
    if use_langfuse_dataset:
        data = client.get_dataset(DATASET_NAME).items
    else:
        data = [
            {
                "input": {"claim": c["claim"]},
                "expected_output": {"expected_verdict": c["expected_verdict"]},
                "metadata": {"golden_id": c["id"], "category": c["category"], "target_entity": c.get("target_entity")},
            }
            for c in claims or []
        ]

    result = client.run_experiment(
        name=DATASET_NAME,
        run_name=run_name,
        data=data,
        task=make_task(check_fn),
        evaluators=[make_evaluator()],
        max_concurrency=1,
    )
    summary = summarize(result)
    return summary, check_gate(summary, thresholds)
