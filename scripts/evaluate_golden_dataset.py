"""Script para avaliação completa do Golden Dataset v1 na Pipeline Multiagente."""

import json
import logging
import sys
import time
from pathlib import Path

# Adiciona a raiz do projeto ao sys.path se necessário
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import FactCheckingPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("Eval.GoldenDataset")


def run_evaluation():
    dataset_path = PROJECT_ROOT / "golden_dataset_v1.json"
    if not dataset_path.exists():
        print(f"Erro: Arquivo {dataset_path} não encontrado.")
        return

    with open(dataset_path, "r", encoding="utf-8") as f:
        claims = json.load(f)

    pipeline = FactCheckingPipeline()
    results = []

    print("=" * 80)
    print(f"INICIANDO AVALIAÇÃO DE {len(claims)} ALEGAÇÕES DO GOLDEN DATASET V1")
    print("=" * 80)

    correct_count = 0
    t_start_total = time.perf_counter()

    for item in claims:
        cid = item["id"]
        claim_text = item["claim"]
        expected = item["expected_verdict"].upper()
        category = item.get("category", "N/A")

        print(f"\n[{cid:02d}/30] [{category}] {claim_text}")
        try:
            res = pipeline.verify(claim_text)
            actual = res.get("verdict", "INCONCLUSIVO").upper()
            is_correct = (actual == expected)
            if is_correct:
                correct_count += 1

            latency = res.get("latency_seconds", {})
            total_sec = latency.get("total", 0.0)

            status_str = "✅ CORRETO" if is_correct else "❌ DIVERGÊNCIA"
            print(f"       Esperado: {expected} | Obtido: {actual} -> {status_str} (Tempo: {total_sec:.2f}s)")
            print(f"       Explicação: {res.get('explanation', '')[:120]}...")

            item_result = {
                "id": cid,
                "claim": claim_text,
                "category": category,
                "expected_verdict": expected,
                "actual_verdict": actual,
                "match": is_correct,
                "explanation": res.get("explanation"),
                "sources_cited": res.get("sources_cited"),
                "plan": res.get("plan"),
                "latency_seconds": latency,
            }
            results.append(item_result)

        except Exception as e:
            logger.error("Erro fatal ao avaliar claim %d: %s", cid, e)
            results.append({
                "id": cid,
                "claim": claim_text,
                "category": category,
                "expected_verdict": expected,
                "actual_verdict": "ERRO",
                "match": False,
                "error": str(e),
            })

    total_time = time.perf_counter() - t_start_total
    accuracy = (correct_count / len(claims)) * 100

    print("\n" + "=" * 80)
    print("RESUMO FINAL DA AVALIAÇÃO")
    print("=" * 80)
    print(f"Total de Alegações: {len(claims)}")
    print(f"Vereditos Corretos: {correct_count} / {len(claims)}")
    print(f"Acurácia Geral: {accuracy:.1f}%")
    print(f"Tempo Total: {total_time:.1f}s (Média por claim: {total_time/len(claims):.1f}s)")

    # Matriz de acertos por categoria
    cat_summary = {}
    for r in results:
        cat = r.get("category", "OUTRO")
        if cat not in cat_summary:
            cat_summary[cat] = {"total": 0, "correct": 0}
        cat_summary[cat]["total"] += 1
        if r.get("match"):
            cat_summary[cat]["correct"] += 1

    print("\nAcurácia por Categoria:")
    for cat, data in cat_summary.items():
        cat_acc = (data["correct"] / data["total"]) * 100
        print(f" - {cat}: {data['correct']}/{data['total']} ({cat_acc:.1f}%)")

    # Salva resultado consolidado
    out_path = PROJECT_ROOT / "benchmark_results_golden_v1.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "total_claims": len(claims),
                "correct_count": correct_count,
                "accuracy_percent": accuracy,
                "total_time_seconds": total_time,
                "average_time_per_claim_seconds": total_time / len(claims),
                "categories": cat_summary,
                "results": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\nResultados detalhados gravados em: {out_path}")


if __name__ == "__main__":
    run_evaluation()
