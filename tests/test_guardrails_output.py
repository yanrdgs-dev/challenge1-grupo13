"""Testes unitários para Output Rails Determinísticos (Regra 1 de AGENTS.md).

Ciclo TDD - Etapa RED / Validação de Latência e Evidência Rastreável.
"""

import time
import pytest
from src.guardrails.actions import audit_traceable_evidence


def test_output_rail_blocks_verdict_without_tool_execution():
    """Valida que respostas VERDADEIRO ou FALSO sem tool executada viram INCONCLUSIVO (Regra 1)."""
    res = audit_traceable_evidence(
        verdict="VERDADEIRO",
        text="A alegação é verdadeira de acordo com fatos históricos.",
        sources=["Fonte Histórica"],
        tool_executed=False,
    )

    assert res["passed"] is False
    assert res["final_verdict"] == "INCONCLUSIVO"
    assert "Regra 1" in res["audit_note"]


def test_output_rail_blocks_verdict_without_primary_source():
    """Valida que respostas sem fonte primária oficial viram INCONCLUSIVO."""
    res = audit_traceable_evidence(
        verdict="FALSO",
        text="O deputado não gastou isso.",
        sources=[],
        tool_executed=True,
    )

    assert res["passed"] is False
    assert res["final_verdict"] == "INCONCLUSIVO"


def test_output_rail_blocks_hallucinated_text_without_source_citation():
    """Valida bloqueio quando o texto não cita expressamente a fonte primária retornada pela tool."""
    res = audit_traceable_evidence(
        verdict="VERDADEIRO",
        text="O parlamentar tem direito ao benefício mensal irrestrito de alimentação.",
        sources=["Ato da Mesa Diretora nº 43/2009"],
        tool_executed=True,
    )

    assert res["passed"] is False
    assert res["final_verdict"] == "INCONCLUSIVO"
    assert "fonte primária oficial" in res["audit_note"]


def test_output_rail_approves_verified_claim_with_tool_and_source():
    """Valida que resposta com tool executada e fonte primária citada é aprovada com louvor."""
    res = audit_traceable_evidence(
        verdict="VERDADEIRO",
        text="De acordo com o Ato da Mesa Diretora nº 43/2009 da Câmara dos Deputados, o limite é fixado regimentalmente.",
        sources=["Ato da Mesa Diretora nº 43/2009"],
        tool_executed=True,
    )

    assert res["passed"] is True
    assert res["final_verdict"] == "VERDADEIRO"


def test_output_rail_always_passes_inconclusive():
    """Valida que veredito INCONCLUSIVO é sempre aceito sem bloqueio de fonte primária."""
    res = audit_traceable_evidence(
        verdict="INCONCLUSIVO",
        text="Não há dados suficientes para determinar a alegação.",
        sources=[],
        tool_executed=False,
    )

    assert res["passed"] is True
    assert res["final_verdict"] == "INCONCLUSIVO"


def test_output_rail_latency_is_under_5ms():
    """Garante que a auditoria determinística do Output Rail roda em menos de 5ms."""
    start = time.perf_counter()
    _ = audit_traceable_evidence(
        verdict="VERDADEIRO",
        text="Conforme a Constituição Federal de 1988, art. 52, a sabatina é pública e o voto é secreto no Senado.",
        sources=["Constituição Federal de 1988"],
        tool_executed=True,
    )
    duration_ms = (time.perf_counter() - start) * 1000.0

    assert duration_ms < 5.0, f"Latência de {duration_ms:.2f}ms ultrapassou o teto de 5ms"
