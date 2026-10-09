"""Testes E2E de validação dos Guardrails com o Golden Dataset (golden_dataset_v1.json).

Portão de Aceite da Regra 5 e Regra 3 de AGENTS.md.
"""

import json
import time
from pathlib import Path
import pytest
from src.guardrails.service import FactCheckingGuardrails

DATASET_PATH = Path("golden_dataset_v1.json")


@pytest.fixture
def golden_dataset():
    assert DATASET_PATH.exists(), "golden_dataset_v1.json não encontrado"
    with open(DATASET_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def guardrails_service():
    return FactCheckingGuardrails()


def test_golden_dataset_inconclusive_claims_blocked_by_guardrails(golden_dataset, guardrails_service):
    """Valida que todas as claims com expected_verdict == INCONCLUSIVO (IDs 25 a 30)

    são barradas com precisão pelo Input Rail sem acionar ferramentas desnecessárias.
    """
    inconclusive_claims = [item for item in golden_dataset if item["expected_verdict"] == "INCONCLUSIVO"]
    assert len(inconclusive_claims) == 6, f"Esperado 6 claims inconclusivas, obtido {len(inconclusive_claims)}"

    for item in inconclusive_claims:
        start = time.perf_counter()
        result = guardrails_service.evaluate(item["claim"])
        latency_ms = (time.perf_counter() - start) * 1000.0

        assert result.verdict == "INCONCLUSIVO", (
            f"Claim {item['id']} ('{item['claim']}') esperava INCONCLUSIVO, obteve {result.verdict}"
        )
        assert result.audit_passed is True
        assert latency_ms < 50.0, f"Claim {item['id']} demorou {latency_ms:.2f}ms (> 50ms)"


def test_golden_dataset_factual_institutional_claims(golden_dataset, guardrails_service):
    """Valida claims factuais institucionais mapeadas no Golden Dataset."""
    # ID 1: Pompeo de Mattos (CEAP 2023)
    item_1 = next(item for item in golden_dataset if item["id"] == 1)
    res_1 = guardrails_service.evaluate(item_1["claim"])
    assert res_1.verdict == "VERDADEIRO"
    assert res_1.audit_passed is True
    assert len(res_1.sources) > 0

    # ID 2: CEAPS Consultoria
    item_2 = next(item for item in golden_dataset if item["id"] == 2)
    res_2 = guardrails_service.evaluate(item_2["claim"])
    assert res_2.verdict == "VERDADEIRO"
    assert res_2.audit_passed is True
    assert any("Regulamento Administrativo" in s for s in res_2.sources)

    # ID 3: Portal da Transparência diárias
    item_3 = next(item for item in golden_dataset if item["id"] == 3)
    res_3 = guardrails_service.evaluate(item_3["claim"])
    assert res_3.verdict == "VERDADEIRO"
    assert res_3.audit_passed is True

    # ID 9: TSE Gastos de campanha
    item_9 = next(item for item in golden_dataset if item["id"] == 9)
    res_9 = guardrails_service.evaluate(item_9["claim"])
    assert res_9.verdict == "VERDADEIRO"
    assert res_9.audit_passed is True


def test_guardrails_end_to_end_latency_is_under_50ms(guardrails_service):
    """Garante que a latência de avaliação é ordens de grandeza inferior ao limite de 3000ms."""
    query = "O valor da cota parlamentar é fixo em R$ 500 para combustível?"
    start = time.perf_counter()
    res = guardrails_service.evaluate(query)
    total_ms = (time.perf_counter() - start) * 1000.0

    assert total_ms < 50.0, f"Tempo de resposta total ({total_ms:.2f}ms) ultrapassou 50ms"
    assert res.audit_passed is True
