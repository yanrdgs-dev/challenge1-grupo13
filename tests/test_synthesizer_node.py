"""Testes unitários para o Nó Sintetizador com Closed-Book Grounding Prompt (Task 2.6).

Atende rigorosamente aos critérios de aceite:
1. Implementação do nó synthesizer_node em src/agents/nodes/synthesizer.py.
2. Prompt com diretrizes fechadas: proibição de suposições e obrigatoriedade de citação dos números retornados.
3. Retorno compulsório de veredito INCONCLUSIVO caso o payload das ferramentas indique ausência de registros.
4. Saída estruturada contendo: verdict (VERDADEIRO, FALSO, INCONCLUSIVO), confidence_score (float),
   explanation (str) e sources (list[str]).
"""

import json
from unittest.mock import MagicMock
import pytest

from src.agents.nodes.synthesizer import (
    CLOSED_BOOK_SYSTEM_PROMPT,
    SynthesizerOutput,
    build_synthesizer_prompt,
    is_empty_payload,
    synthesizer_node,
)


# ---------------------------------------------------------------------------
# 1. Testes de Diretrizes do Prompt Closed-Book Grounding
# ---------------------------------------------------------------------------

def test_closed_book_prompt_contains_mandatory_grounding_rules():
    """Valida que o prompt do sistema proíbe suposições/conhecimento externo e exige números."""
    prompt = CLOSED_BOOK_SYSTEM_PROMPT

    # Proibição de suposições e conhecimento externo
    assert "conhecimento externo" in prompt.lower() or "suposiç" in prompt.lower()
    assert "estritamente" in prompt.lower() or "fechado" in prompt.lower()

    # Obrigatoriedade de citação de números/valores
    assert "número" in prompt.lower() or "valores" in prompt.lower() or "dados numéricos" in prompt.lower()

    # Vereditos permitidos
    assert "VERDADEIRO" in prompt
    assert "FALSO" in prompt
    assert "INCONCLUSIVO" in prompt


def test_build_synthesizer_prompt_injects_claim_and_evidence():
    """Valida a injeção estrita da alegação e das evidências no contexto fechado."""
    claim = "Deputado X gastou R$ 50.000 em passagens."
    evidences = [
        {
            "tool": "check_parliamentary_expenses",
            "status": "success",
            "data": {"valor_total": 50000.0, "qtd_lancamentos": 12, "casa": "camara"},
        }
    ]

    full_prompt = build_synthesizer_prompt(claim, evidences)

    assert claim in full_prompt
    assert "50000" in full_prompt or "50.000" in full_prompt
    assert "check_parliamentary_expenses" in full_prompt or "camara" in full_prompt


# ---------------------------------------------------------------------------
# 2. Testes de Retorno Compulsório INCONCLUSIVO (Ausência de Registros)
# ---------------------------------------------------------------------------

def test_synthesizer_node_empty_evidences_returns_inconclusivo_immediately():
    """Valida que payload sem nenhuma evidência retorna INCONCLUSIVO sem invocar o LLM."""
    mock_llm = MagicMock()
    state = {
        "claim": "Um deputado gastou muito dinheiro no ano passado.",
        "evidences": [],
    }

    result = synthesizer_node(state, llm_client=mock_llm)

    assert result["verdict"] == "INCONCLUSIVO"
    assert isinstance(result["confidence_score"], float)
    assert result["confidence_score"] >= 0.9
    assert isinstance(result["explanation"], str)
    assert len(result["explanation"]) > 0
    assert isinstance(result["sources"], list)
    assert not mock_llm.generate.called


def test_synthesizer_node_zero_records_returns_inconclusivo_compulsorily():
    """Valida retorno compulsório quando ferramentas retornam 0 lançamentos/registros."""
    mock_llm = MagicMock()
    state = {
        "claim": "Deputado Fulano gastou R$ 20.000 em combustíveis.",
        "evidences": [
            {
                "tool": "check_parliamentary_expenses",
                "status": "success",
                "data": {
                    "qtd_lancamentos": 0,
                    "valor_total": 0.0,
                    "registros": [],
                },
            }
        ],
    }

    result = synthesizer_node(state, llm_client=mock_llm)

    assert result["verdict"] == "INCONCLUSIVO"
    assert result["confidence_score"] >= 0.9
    assert "nenhum registro" in result["explanation"].lower() or "ausência" in result["explanation"].lower()
    assert not mock_llm.generate.called


def test_synthesizer_node_tool_error_or_not_found_returns_inconclusivo():
    """Valida retorno compulsório quando as ferramentas retornam erro ou status de não encontrado."""
    mock_llm = MagicMock()
    state = {
        "claim": "Deputado Inexistente votou a favor da PEC.",
        "evidences": [
            {
                "tool": "resolve_politician",
                "status": "not_found",
                "data": {"encontrado": False, "candidato": None},
            }
        ],
    }

    result = synthesizer_node(state, llm_client=mock_llm)

    assert result["verdict"] == "INCONCLUSIVO"
    assert not mock_llm.generate.called


def test_synthesizer_node_empty_claim_returns_inconclusivo():
    """Valida retorno de INCONCLUSIVO para alegação vazia ou em branco."""
    mock_llm = MagicMock()
    state = {"claim": "   ", "evidences": [{"tool": "dummy", "status": "success", "data": {}}]}

    result = synthesizer_node(state, llm_client=mock_llm)

    assert result["verdict"] == "INCONCLUSIVO"
    assert not mock_llm.generate.called


# ---------------------------------------------------------------------------
# 3. Testes do Caminho Feliz e Saída Estruturada
# ---------------------------------------------------------------------------

def test_synthesizer_node_happy_path_verdadeiro():
    """Valida veredito VERDADEIRO com citação obrigatória de números e fontes."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "verdict": "VERDADEIRO",
        "confidence_score": 0.98,
        "explanation": "Pompeo de Mattos liderou os gastos da CEAP em 2023 totalizando R$ 540.000,00.",
        "sources": ["Câmara dos Deputados - CEAP 2023"],
    })

    state = {
        "claim": "Em 2023, o deputado que mais gastou a CEAP foi Pompeo de Mattos.",
        "evidences": [
            {
                "tool": "get_top_ceap_spender",
                "status": "success",
                "data": {
                    "casa": "camara",
                    "ano": 2023,
                    "gastadores": [
                        {
                            "nome_parlamentar": "POMPEO DE MATTOS",
                            "valor_total": 540000.0,
                            "partido": "PDT",
                            "uf": "RS",
                        }
                    ],
                },
            }
        ],
    }

    result = synthesizer_node(state, llm_client=mock_llm)

    assert result["verdict"] == "VERDADEIRO"
    assert isinstance(result["confidence_score"], float)
    assert result["confidence_score"] == 0.98
    assert "540.000" in result["explanation"] or "540000" in result["explanation"]
    assert "Câmara dos Deputados - CEAP 2023" in result["sources"]
    assert mock_llm.generate.called


def test_synthesizer_node_happy_path_falso():
    """Valida veredito FALSO confrontando os números da votação."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "verdict": "FALSO",
        "confidence_score": 0.95,
        "explanation": "A votação do Marco Temporal não foi unânime; houve 155 votos contrários registrados no Plenário.",
        "sources": ["Câmara dos Deputados - Votações Nominais 2023"],
    })

    state = {
        "claim": "A votação do Marco Temporal na Câmara foi unânime sem nenhum voto contra.",
        "evidences": [
            {
                "tool": "get_proposition_vote_result",
                "status": "success",
                "data": {
                    "aprovado": True,
                    "unanimidade": False,
                    "votos_sim": 283,
                    "votos_nao": 155,
                },
            }
        ],
    }

    result = synthesizer_node(state, llm_client=mock_llm)

    assert result["verdict"] == "FALSO"
    assert isinstance(result["confidence_score"], float)
    assert "155" in result["explanation"]
    assert result["sources"] == ["Câmara dos Deputados - Votações Nominais 2023"]


def test_synthesizer_node_handles_markdown_fence_in_llm_response():
    """Valida robustez contra LLMs que envolvem JSON em blocos ```json."""
    mock_llm = MagicMock()
    raw_markdown = """```json
{
  "verdict": "VERDADEIRO",
  "confidence_score": 0.92,
  "explanation": "O teto para combustíveis ultrapassa R$ 6.000 mensais.",
  "sources": ["Ato da Mesa da Câmara"]
}
```"""
    mock_llm.generate.return_value = raw_markdown

    state = {
        "claim": "Existe teto de combustíveis para deputados.",
        "evidences": [
            {
                "tool": "check_institutional_rule",
                "status": "success",
                "data": {"teto_valor": 6000.0, "topico": "combustivel"},
            }
        ],
    }

    result = synthesizer_node(state, llm_client=mock_llm)

    assert result["verdict"] == "VERDADEIRO"
    assert result["confidence_score"] == 0.92
    assert "6.000" in result["explanation"]
    assert result["sources"] == ["Ato da Mesa da Câmara"]


def test_synthesizer_node_invalid_llm_json_fallback_graceful():
    """Valida comportamento seguro quando a resposta do LLM é completamente truncada/inválida."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "Erro interno no servidor de modelo."

    state = {
        "claim": "Alegação de teste para fallback.",
        "evidences": [
            {
                "tool": "check_parliamentary_expenses",
                "status": "success",
                "data": {"valor_total": 100.0, "qtd_lancamentos": 1},
            }
        ],
    }

    result = synthesizer_node(state, llm_client=mock_llm)

    # Não deve lançar exceção, deve devolver estrutura segura e INCONCLUSIVO
    assert result["verdict"] == "INCONCLUSIVO"
    assert isinstance(result["confidence_score"], float)
    assert isinstance(result["explanation"], str)
    assert isinstance(result["sources"], list)
