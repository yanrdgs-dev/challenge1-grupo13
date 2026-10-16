"""Compara só o roteamento (qual tool o LLM escolhe) entre modelos e estratégias, sem executar tools nem julgar.

Uso manual, com o Ollama ligado:
    uv run python scripts/compare_routing.py
    uv run python scripts/compare_routing.py --variants 7b-full,7b-2etapas --limit 10

Mede, nas claims do golden dataset que esperam VERDADEIRO ou FALSO, quantas vezes a tool escolhida pertence à
categoria da claim (mesma regra do scorer ``tool_category_match``). É a escolha crua do LLM: não passa pelos
guardas do router, para isolar o efeito do modelo e do catálogo.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.llm_client import LLMClient  # noqa: E402
from src.evaluation.scorers import ALLOWED_TOOLS  # noqa: E402
from src.services.category_routing import classify_claim, restrict_catalog  # noqa: E402
from src.services.tool_catalog import ROUTER_SYSTEM_PROMPT, TOOLS_CATALOG  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# nome -> (modelo, duas etapas?)
VARIANTS = {
    "7b-full": ("qwen2.5:7b", False),
    "7b-2etapas": ("qwen2.5:7b", True),
    "14b-full": ("qwen2.5:14b", False),
    "14b-2etapas": ("qwen2.5:14b", True),
}


def load_claims(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("claims", data)


def choose_tool(client: LLMClient, model: str, claim: str, two_stage: bool) -> Dict[str, Any]:
    catalog = TOOLS_CATALOG
    category: Optional[str] = None
    if two_stage:
        category = classify_claim(lambda msgs: client.chat(msgs, model=model, json_mode=True), claim)
        catalog = restrict_catalog(TOOLS_CATALOG, category)
    try:
        result = client.chat(
            [{"role": "system", "content": ROUTER_SYSTEM_PROMPT}, {"role": "user", "content": claim}],
            tools=catalog, model=model,
        )
    except Exception as exc:
        return {"tool": None, "categoria": category, "erro": str(exc)[:80]}
    calls = result.tool_calls or []
    return {"tool": calls[0]["name"] if calls else None, "categoria": category, "erro": None}


def run_variant(name: str, claims: List[Dict[str, Any]], timeout: float) -> Dict[str, Any]:
    model, two_stage = VARIANTS[name]
    client = LLMClient(timeout=timeout, role="router")
    rows, started = [], time.perf_counter()
    for claim in claims:
        t0 = time.perf_counter()
        choice = choose_tool(client, model, claim["claim"], two_stage)
        category = claim["category"]
        ok = choice["tool"] in ALLOWED_TOOLS.get(category, frozenset())
        rows.append({"id": claim["id"], "category": category, "expected": claim["expected_verdict"], **choice,
                     "ok": ok, "s": round(time.perf_counter() - t0, 1)})
        print(f"[{name}] #{claim['id']:>2} {category:9} -> {choice['tool']} {'OK' if ok else '--'}", flush=True)
    return {"variant": name, "model": model, "two_stage": two_stage,
            "total_s": round(time.perf_counter() - started, 1), "rows": rows}


def summarize(result: Dict[str, Any]) -> str:
    rows = [r for r in result["rows"] if r["expected"] != "INCONCLUSIVO"]
    ok = sum(r["ok"] for r in rows)
    no_tool = sum(r["tool"] is None for r in rows)
    errors = sum(bool(r["erro"]) for r in rows)
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r["ok"])
    cats = ", ".join(f"{c} {sum(v)}/{len(v)}" for c, v in sorted(by_cat.items()))
    mean_s = sum(r["s"] for r in result["rows"]) / max(len(result["rows"]), 1)
    return (f"{result['variant']:12} tool_category_match {ok}/{len(rows)} = {ok / max(len(rows), 1):.1%} | "
            f"sem tool {no_tool} | erros {errors} | {cats} | {mean_s:.1f}s/claim")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variants", default="7b-full,7b-2etapas,14b-full")
    parser.add_argument("--limit", type=int, default=0, help="Só as N primeiras claims (0 = todas).")
    parser.add_argument("--dataset", default=str(ROOT / "golden_dataset_v2.json"))
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--out", default=None, help="Arquivo JSON com as escolhas de cada claim.")
    args = parser.parse_args(argv)

    claims = [c for c in load_claims(Path(args.dataset)) if c["expected_verdict"] != "INCONCLUSIVO"]
    if args.limit:
        claims = claims[: args.limit]
    names = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = [n for n in names if n not in VARIANTS]
    if unknown:
        print(f"Variante desconhecida: {unknown}. Opções: {list(VARIANTS)}", file=sys.stderr)
        return 2

    results = []
    for name in names:
        results.append(run_variant(name, claims, args.timeout))
        print("\n" + summarize(results[-1]) + "\n", flush=True)
    print("=== RESUMO ===")
    for result in results:
        print(summarize(result))
    if args.out:
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
