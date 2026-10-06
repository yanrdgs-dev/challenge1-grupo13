"""Testes unitários para o módulo de agentes e pipeline de fact-checking."""

import json
from unittest.mock import MagicMock
import pytest

from src.agents.orchestrator import OrchestratorAgent
from src.agents.synthesizer import SynthesizerAgent
from src.agents.pipeline import FactCheckingPipeline


def test_orchestrator_empty_claim():
    """Valida que alegações vazias resultam imediatamente em INCONCLUSIVO sem chamar LLM."""
    mock_llm = MagicMock()
    orchestrator = OrchestratorAgent(llm_client=mock_llm)

    result = orchestrator.plan("")
    assert result["action"] == "direct_verdict"
    assert result["verdict"] == "INCONCLUSIVO"
    assert not mock_llm.generate.called


def test_orchestrator_vague_claim_direct_verdict():
    """Valida planejamento de alegações vagas/subespecificadas."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "action": "direct_verdict",
        "verdict": "INCONCLUSIVO",
        "reasoning": "Alegação genérica sem identificação do deputado."
    })
    orchestrator = OrchestratorAgent(llm_client=mock_llm)

    plan = orchestrator.plan("Um deputado qualquer gastou muito dinheiro.")
    assert plan["action"] == "direct_verdict"
    assert plan["verdict"] == "INCONCLUSIVO"
    assert mock_llm.generate.called


def test_orchestrator_valid_claim_plans_tools():
    """Valida planejamento de ferramentas para alegação verificável."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "action": "call_tools",
        "reasoning": "Alegação específica sobre gastos na Câmara.",
        "steps": [
            {
                "tool": "resolve_politician",
                "params": {"nome_busca": "Pompeo de Mattos", "uf": "RS"}
            },
            {
                "tool": "get_top_ceap_spender",
                "params": {"casa": "camara", "ano": 2023, "top_n": 1}
            }
        ]
    })
    orchestrator = OrchestratorAgent(llm_client=mock_llm)

    plan = orchestrator.plan("Em 2023, o deputado que mais gastou a CEAP foi Pompeo de Mattos.")
    assert plan["action"] == "call_tools"
    assert len(plan["steps"]) == 2
    assert plan["steps"][0]["tool"] == "resolve_politician"
    assert plan["steps"][1]["tool"] == "get_top_ceap_spender"


def test_synthesizer_empty_claim():
    """Valida retorno inconclusivo para alegação vazia no sintetizador."""
    mock_llm = MagicMock()
    synthesizer = SynthesizerAgent(llm_client=mock_llm)

    result = synthesizer.synthesize("", [])
    assert result["verdict"] == "INCONCLUSIVO"
    assert not mock_llm.generate.called


def test_synthesizer_generates_verdict():
    """Valida emissão de veredito pelo sintetizador."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "verdict": "VERDADEIRO",
        "confidence": "ALTA",
        "explanation": "Dados da CEAP comprovam que Pompeo de Mattos liderou os gastos em 2023.",
        "sources_cited": ["Câmara dos Deputados - CEAP 2023"]
    })
    synthesizer = SynthesizerAgent(llm_client=mock_llm)

    evidences = [
        {
            "tool": "get_top_ceap_spender",
            "status": "success",
            "data": {
                "top_spenders": [
                    {"nome_parlamentar": "POMPEO DE MATTOS", "valor_total": 540000.0}
                ]
            }
        }
    ]

    result = synthesizer.synthesize("Pompeo de Mattos foi o maior gastador em 2023", evidences)
    assert result["verdict"] == "VERDADEIRO"
    assert result["confidence"] == "ALTA"
    assert "Câmara dos Deputados - CEAP 2023" in result["sources_cited"]


def test_pipeline_direct_verdict_bypasses_tools():
    """Valida que veredito direto do orquestrador não invoca tools nem sintetizador."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "action": "direct_verdict",
        "verdict": "INCONCLUSIVO",
        "reasoning": "Subespecificada."
    })

    tool_mock = MagicMock()
    pipeline = FactCheckingPipeline(
        llm_client=mock_llm,
        tool_registry={"some_tool": tool_mock}
    )

    res = pipeline.verify("Boato qualquer sem fonte.")
    assert res["verdict"] == "INCONCLUSIVO"
    assert not tool_mock.called
    assert res["evidences"] == []


def test_pipeline_executes_tools_and_synthesizes():
    """Valida fluxo completo ponta a ponta na pipeline com mock."""
    mock_llm = MagicMock()

    # 1ª chamada = Orquestrador (retorna call_tools)
    # 2ª chamada = Sintetizador (retorna VERDADEIRO)
    mock_llm.generate.side_effect = [
        json.dumps({
            "action": "call_tools",
            "reasoning": "Checar regra da cota.",
            "steps": [
                {
                    "tool": "check_institutional_rule",
                    "params": {"regra_slug": "calculo_cota_por_uf"}
                }
            ]
        }),
        json.dumps({
            "verdict": "VERDADEIRO",
            "confidence": "ALTA",
            "explanation": "A cota varia de acordo com o estado do parlamentar.",
            "sources_cited": ["Ato da Mesa da Câmara dos Deputados"]
        })
    ]

    mock_rule_func = MagicMock(return_value={"regra_valida": True, "uf_varia": True})
    pipeline = FactCheckingPipeline(
        llm_client=mock_llm,
        tool_registry={"check_institutional_rule": mock_rule_func}
    )

    result = pipeline.verify("O valor da cota varia conforme o estado?")
    assert result["verdict"] == "VERDADEIRO"
    assert mock_rule_func.called
    assert len(result["evidences"]) == 1
    assert result["evidences"][0]["status"] == "success"


def test_pipeline_handles_tool_failure_gracefully():
    """Valida que falhas em tools são capturadas e repassadas como evidência de erro."""
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [
        json.dumps({
            "action": "call_tools",
            "steps": [{"tool": "falha_tool", "params": {}}]
        }),
        json.dumps({
            "verdict": "INCONCLUSIVO",
            "confidence": "BAIXA",
            "explanation": "Ferramenta falhou ao consultar base.",
            "sources_cited": []
        })
    ]

    def falha_func():
        raise RuntimeError("Conexão perdida")

    pipeline = FactCheckingPipeline(
        llm_client=mock_llm,
        tool_registry={"falha_tool": falha_func}
    )

    res = pipeline.verify("Teste de erro")
    assert res["verdict"] == "INCONCLUSIVO"
    assert res["evidences"][0]["status"] == "error"
    assert "Conexão perdida" in res["evidences"][0]["error"]
