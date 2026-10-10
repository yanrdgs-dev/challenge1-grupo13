"""Roda as 30 claims do golden dataset contra o router e aplica o gate de aceite (regra 5).

Exemplos:
    uv run python scripts/run_golden_experiment.py --run-name baseline
    uv run python scripts/run_golden_experiment.py --dataset langfuse --threshold verdict_match=0.8

Código de saída: 0 = gate aprovado, 1 = gate reprovado, 2 = erro de uso ou de infraestrutura.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.dataset import load_golden_dataset  # noqa: E402
from src.evaluation.experiment import (  # noqa: E402
    RouterClient,
    format_confusion_matrix,
    load_thresholds,
    parse_threshold_args,
    run_golden_experiment,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_THRESHOLDS_FILE = ROOT / "evaluation" / "thresholds.json"


def _langfuse_client():
    from dotenv import load_dotenv
    from langfuse import get_client

    load_dotenv()
    return get_client()


def _router_check_fn(url: str, session_id: str) -> Callable:
    return RouterClient(url, session_id=session_id)


def _default_run_name() -> str:
    return f"golden-{os.getenv('GIT_SHA') or time.strftime('%Y%m%d-%H%M%S')}"


def _print_report(summary: dict, problems: List[str]) -> None:
    print(f"\nRun: {summary['run_name']}  |  claims: {summary['total']}")
    if summary.get("dataset_run_url"):
        print(f"Langfuse: {summary['dataset_run_url']}")
    print("\nMatriz de confusão (linhas = esperado, colunas = obtido):")
    print(format_confusion_matrix(summary["matrix"]))
    print("\nScores:")
    for name, stats in sorted(summary["scores"].items()):
        print(f"  {name:<28} {stats['mean']:>7.1%}   (n={stats['n']})")
    if summary["failures"]:
        print("\nClaims com veredito diferente do esperado:")
        for f in summary["failures"]:
            detail = f"  #{f['golden_id']}: esperado {f['expected']}, obtido {f['got']}"
            if f.get("erro"):
                detail += f"  [{f['erro']}]"
            if f.get("trace_id"):
                detail += f"  trace={f['trace_id']}"
            print(detail)
    if problems:
        print("\nGATE REPROVADO:")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("\nGATE APROVADO")


def main(
    argv: Optional[List[str]] = None,
    client_factory: Callable = _langfuse_client,
    check_fn_factory: Callable = _router_check_fn,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--router-url", default=os.getenv("ROUTER_URL", "http://localhost:8000"))
    parser.add_argument("--run-name", default=None, help="Nome da execução (padrão: golden-<GIT_SHA|data>).")
    parser.add_argument("--dataset", choices=["langfuse", "local"], default="langfuse",
                        help="Origem das claims: dataset no Langfuse (vincula a execução) ou arquivo local.")
    parser.add_argument("--local", action="store_true", help="Atalho para --dataset local.")
    parser.add_argument("--golden-path", default=str(ROOT / "golden_dataset_v2.json"),
                        help="Arquivo do golden; o nome do dataset no Langfuse é o do arquivo (golden_dataset_v1/v2).")
    parser.add_argument("--threshold", action="append", default=[], metavar="NOME=VALOR",
                        help="Limiar mínimo (0 a 1) de um score. Pode repetir.")
    parser.add_argument("--thresholds-file", default=str(DEFAULT_THRESHOLDS_FILE))
    parser.add_argument("--json-out", default=None, help="Grava o resumo em JSON neste caminho.")
    args = parser.parse_args(argv)

    run_name = args.run_name or _default_run_name()
    use_dataset = args.dataset == "langfuse" and not args.local

    try:
        thresholds = load_thresholds(args.thresholds_file)
        thresholds.update(parse_threshold_args(args.threshold))
        claims = None if use_dataset else load_golden_dataset(args.golden_path)
        client = client_factory()
        check_fn = check_fn_factory(args.router_url, f"golden-{run_name}")
        summary, problems = run_golden_experiment(
            client, claims, check_fn, run_name, thresholds, use_langfuse_dataset=use_dataset,
            dataset_name=Path(args.golden_path).stem,
        )
    except ValueError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERRO de execução: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    _print_report(summary, problems)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        client.flush()
    except Exception:
        pass
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
