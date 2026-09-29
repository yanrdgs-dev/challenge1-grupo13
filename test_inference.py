"""Script de validação de conectividade, inferência e latência."""

import sys
import time
from src.core.llm_client import LLMClient


def test_inference() -> bool:
    """Executa teste de inferência e valida critérios de aceitação."""
    print("\n==================================================")
    print("  TESTE DE INFERÊNCIA E LATÊNCIA (AI/CORE 1.6)   ")
    print("==================================================")

    client = LLMClient()
    prompt = "Responda apenas 'OK' em caixa alta."

    print(f"Provedor configurado: {client.primary_provider.upper()}")
    print(f"Provedor de fallback: {client.fallback_provider.upper()}")
    print(f"Prompt enviado: '{prompt}'")
    print("Aguardando resposta do modelo...")

    start_time = time.time()
    try:
        result = client.generate(prompt)
    except Exception as e:
        print(f"\n[ERRO] Falha durante a inferência: {e}")
        return False

    elapsed = time.time() - start_time

    print("\n--- Resultado da Inferência ---")
    print(f"Resposta: {result.strip()}")
    print(f"Tempo de execução: {elapsed:.2f}s")

    if elapsed < 3.0:
        print("✓ Latência menor que 3 segundos (Critério de Aceite: Aprovado)")
        success = True
    else:
        print("⚠ AVISO: Latência acima do limite de 3s")
        success = False

    return success


if __name__ == "__main__":
    passed = test_inference()
    sys.exit(0 if passed else 1)
