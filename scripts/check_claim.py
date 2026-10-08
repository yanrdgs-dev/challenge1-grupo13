#!/usr/bin/env python3
"""CLI Interativo para Fact-Checking de Alegações Políticas.

Permite que o usuário passe uma alegação por argumento de linha de comando
ou digite interativamente perguntas para verificação imediata.

Exemplos de uso:
    .venv/bin/python scripts/check_claim.py "Deputados podem pedir reembolso de alimentação com a cota?"
    .venv/bin/python scripts/check_claim.py
"""

import argparse
import sys
import time
from pathlib import Path

# Garante que a raiz do projeto esteja no sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import FactCheckingPipeline


def format_verdict(verdict: str) -> str:
    """Formata o veredito com destaque visual."""
    v = verdict.upper()
    if v == "VERDADEIRO":
        return "✅ VERDADEIRO"
    elif v == "FALSO":
        return "❌ FALSO"
    elif v == "INCONCLUSIVO":
        return "⚠️  INCONCLUSIVO"
    return f"❓ {verdict}"


def check_and_display(pipeline: FactCheckingPipeline, claim: str):
    """Executa a verificação e exibe o resultado formatado."""
    claim = claim.strip()
    if not claim:
        print("Alegação vazia fornecida. Tente novamente.\n")
        return

    print("\n" + "=" * 70)
    print(f"🔍 ALEGAÇÃO: \"{claim}\"")
    print("=" * 70)
    print("⏳ Analisando alegação e consultando bases oficiais...")

    t0 = time.perf_counter()
    try:
        result = pipeline.verify(claim)
    except Exception as e:
        print(f"\n[ERRO] Falha ao processar alegação: {e}\n")
        return
    total_time = time.perf_counter() - t0

    verdict = result.get("verdict", "INCONCLUSIVO")
    confidence = result.get("confidence", "N/A")
    explanation = result.get("explanation", "Sem explicação.")
    sources = result.get("sources_cited", [])
    plan = result.get("plan", {})
    evidences = result.get("evidences", [])
    latency = result.get("latency_seconds", {})

    print("\n" + "-" * 70)
    print(f"RESULTADO: {format_verdict(verdict)}  (Confiança: {confidence})")
    print("-" * 70)
    print(f"📝 EXPLICAÇÃO:\n   {explanation}\n")

    if sources:
        print("📚 FONTES CITADAS:")
        for s in sources:
            print(f"   • {s}")
        print()

    # Detalhes técnicos do processo
    tools_called = [e.get("tool") for e in evidences if e.get("tool")]
    if tools_called:
        print(f"🛠️  FERRAMENTAS AUDITADAS: {', '.join(tools_called)}")
    elif plan.get("action") == "direct_verdict":
        print("⚡ AÇÃO: Veredito Direto (Fast-Path / Princípio III)")

    orch_t = latency.get("orchestrator", 0.0)
    tools_t = latency.get("tools", 0.0)
    synth_t = latency.get("synthesizer", 0.0)
    tot_t = latency.get("total", total_time)

    print(f"⏱️  TEMPO DE EXECUÇÃO: {tot_t:.2f}s  (Orquestrador: {orch_t:.2f}s | Tools: {tools_t:.2f}s | Sintetizador: {synth_t:.2f}s)")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="CLI Interativo de Fact-Checking Político com Multiagentes (Qwen 2.5)"
    )
    parser.add_argument(
        "claim",
        nargs="?",
        default=None,
        help="Texto da afirmação política a ser checada (opcional; se omitido, entra em modo interativo)",
    )
    args = parser.parse_args()

    print("Iniciando Pipeline de Fact-Checking Multiagente...")
    pipeline = FactCheckingPipeline()
    print("Sistema pronto!\n")

    if args.claim:
        # Modo argumento único
        check_and_display(pipeline, args.claim)
    else:
        # Modo interativo (loop)
        print("=" * 70)
        print("  MODO INTERATIVO DE FACT-CHECKING POLÍTICO")
        print("  Digite sua alegação ou pergunta. Para sair, digite 'sair' ou 'exit'.")
        print("=" * 70)

        while True:
            try:
                user_input = input("\n👉 Digite a alegação: ").strip()
                if user_input.lower() in ("sair", "exit", "quit", "q"):
                    print("Encerrando fact-checking. Até logo!")
                    break
                if not user_input:
                    continue
                check_and_display(pipeline, user_input)
            except (KeyboardInterrupt, EOFError):
                print("\nEncerrando fact-checking. Até logo!")
                break


if __name__ == "__main__":
    main()
