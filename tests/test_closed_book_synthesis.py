"""Bateria de testes de regressão de grounding e anti-alucinação (Task 2.7).

Avalia se o sintetizador respeita estritamente as regras de Closed-Book:
1. Injeção de payload vazio deve obrigatoriamente produzir o veredito INCONCLUSIVO.
2. Pergunta sobre fato histórico notório sem dados injetados na ferramenta não pode ser confirmada pelo modelo.
3. Validação de que 100% dos testes da suíte passam sem quebras de formato JSON.
4. Mocks de ferramentas simulando cenários reais de dados, erros de rede e respostas adversariais.
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
# 1. Cenário: Injeção de Payload Vazio Deve Obrigatoriamente Produzir INCONCLUSIVO
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "empty_evidences_payload",
    [
        [],                                                  # Lista vazia
        None,                                                # None
        [{}],                                                # Dicionário vazio
        [{"tool": "get_top_ceap_spender", "data": {}}],     # Data vazia
        [{"tool": "check_parliamentary_expenses", "status": "success", "data": {"qtd_lancamentos": 0, "valor_total": 0.0, "registros": []}}],
        [{"tool": "get_top_ceap_spender", "status": "success", "data": {"gastadores": []}}],
        [{"tool": "get_proposition_vote_result", "status": "success", "data": {"votacoes": []}}],
        [{"tool": "check_institutional_rule", "status": "success", "data": {"encontrado": False}}],
        [{"tool": "resolve_politician", "status": "not_found", "data": {"candidato": None}}],
        [{"tool": "api_externa", "status": "error", "data": None}],
    ],
)
def test_empty_or_zero_records_payload_compulsorily_yields_inconclusivo(empty_evidences_payload):
    """Valida que qualquer variação de payload vazio/ausente retorna compulsoriamente INCONCLUSIVO sem chamar o LLM."""
    mock_llm = MagicMock()
    state = {
        "claim": "O deputado X utilizou R$ 100.000 da cota parlamentar em 2023.",
        "evidences": empty_evidences_payload,
    }

    result = synthesizer_node(state, llm_client=mock_llm)

    assert result["verdict"] == "INCONCLUSIVO"
    assert isinstance(result["confidence_score"], float)
    assert result["confidence_score"] >= 0.9
    assert isinstance(result["explanation"], str)
    assert len(result["explanation"]) > 0
    assert isinstance(result["sources"], list)
    # Princípio inegociável: nenhuma chamada ao LLM quando não há dados oficiais
    assert not mock_llm.generate.called


def test_is_empty_payload_utility_edge_cases():
    """Valida detecção analítica de ausência de dados em diferentes formatos estruturais."""
    assert is_empty_payload([]) is True
    assert is_empty_payload(None) is True
    assert is_empty_payload({}) is True
    assert is_empty_payload([{"status": "error"}]) is True
    assert is_empty_payload([{"status": "success", "data": {"encontrado": False}}]) is True
    assert is_empty_payload([{"status": "success", "data": {"qtd_lancamentos": 0, "valor_total": 0.0}}]) is True

    # Com registros válidos
    assert is_empty_payload([{"status": "success", "data": {"qtd_lancamentos": 1, "valor_total": 150.0}}]) is False
    assert is_empty_payload([{"status": "success", "data": {"gastadores": [{"nome": "Pompeo"}]}}]) is False


# ---------------------------------------------------------------------------
# 2. Cenário: Fato Histórico Notório Sem Dados Injetados NÃO Pode Ser Confirmado
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "notorious_historical_claim",
    [
        "A Proclamação da República do Brasil ocorreu no dia 15 de novembro de 1889.",
        "A Constituição Cidadã do Brasil foi promulgada em 1988.",
        "O Plano Real foi lançado em 1994 para combater a hiperinflação no Brasil.",
        "Tancredo Neves foi eleito presidente da República pelo Colégio Eleitoral em 1985.",
        "O impeachment do presidente Fernando Collor foi aprovado pela Câmara dos Deputados em 1992.",
        "Dilma Rousseff sofreu processo de impeachment no Senado Federal em 2016.",
        "Juscelino Kubitschek inaugurou a cidade de Brasília como nova capital em 1960.",
    ],
)
def test_notorious_historical_facts_without_tool_data_cannot_be_confirmed(notorious_historical_claim: str):
    """Garante que o sintetizador NÃO use memória paramétrica para validar fatos históricos sem dados oficiais injetados."""
    mock_llm = MagicMock()
    # Se uma implementação falha chamasse o LLM, o LLM poderia querer dizer 'VERDADEIRO' por saber o fato histórico.
    # Mas o guardrail de Closed-Book DEVE impedir a validação e forçar INCONCLUSIVO.
    state = {
        "claim": notorious_historical_claim,
        "evidences": [],  # Ferramentas não possuem registros históricos fora do escopo coberto
    }

    result = synthesizer_node(state, llm_client=mock_llm)

    # Veredito NUNCA pode ser VERDADEIRO baseado na memória do modelo
    assert result["verdict"] != "VERDADEIRO"
    assert result["verdict"] == "INCONCLUSIVO"
    assert not mock_llm.generate.called


def test_closed_book_prompt_instructs_model_against_historical_parametric_knowledge():
    """Valida que o prompt do sistema instrui explicitamente a ignorar conhecimento prévio enciclopédico."""
    claim = "A Lei Áurea foi assinada pela Princesa Isabel em 13 de maio de 1888."
    evidences = [
        {
            "tool": "check_institutional_rule",
            "status": "success",
            "data": {
                "observacao": "Base institucional cobre apenas o regimento da Câmara dos Deputados e do Senado atual."
            },
        }
    ]

    prompt = build_synthesizer_prompt(claim, evidences)

    # Deve conter diretrizes explícitas de grounding fechado
    assert "PROIBIÇÃO ABSOLUTA DE CONHECIMENTO EXTERNO OU SUPOSIÇÕES" in prompt
    assert "memória paramétrica" in prompt.lower() or "conhecimento externo" in prompt.lower()
    assert claim in prompt


# ---------------------------------------------------------------------------
# 3. Cenário: 100% dos Testes Passam Sem Quebras de Formato JSON
# ---------------------------------------------------------------------------

def test_json_output_strict_schema_conformance():
    """Valida conformidade rigorosa da saída estruturada contra o schema SynthesizerOutput."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "verdict": "VERDADEIRO",
        "confidence_score": 0.99,
        "explanation": "O deputado Pompeo de Mattos registrou o maior gasto com R$ 540.000,00.",
        "sources": ["Câmara dos Deputados - CEAP"],
    })

    state = {
        "claim": "Pompeo gastou 540 mil reais em 2023.",
        "evidences": [
            {
                "tool": "get_top_ceap_spender",
                "status": "success",
                "data": {"gastadores": [{"nome_parlamentar": "POMPEO DE MATTOS", "valor_total": 540000.0}]},
            }
        ],
    }

    output = synthesizer_node(state, llm_client=mock_llm)

    # 1. Validação de chaves obrigatórias
    assert set(output.keys()) == {"verdict", "confidence_score", "explanation", "sources"}

    # 2. Tipagem estrita
    assert output["verdict"] in ("VERDADEIRO", "FALSO", "INCONCLUSIVO")
    assert isinstance(output["confidence_score"], float)
    assert 0.0 <= output["confidence_score"] <= 1.0
    assert isinstance(output["explanation"], str) and len(output["explanation"]) > 0
    assert isinstance(output["sources"], list)

    # 3. Serialização JSON garantida sem exceções
    serialized = json.dumps(output)
    deserialized = json.loads(serialized)
    assert deserialized == output


@pytest.mark.parametrize(
    "raw_llm_response,expected_verdict",
    [
        # Markdown fence ```json
        ('```json\n{"verdict": "VERDADEIRO", "confidence_score": 0.95, "explanation": "Confirmado com R$ 10.000.", "sources": ["TSE"]}\n```', "VERDADEIRO"),
        # Markdown fence genérico ```
        ('```\n{"verdict": "FALSO", "confidence_score": 0.90, "explanation": "Refutado com 10 votos.", "sources": ["Senado"]}\n```', "FALSO"),
        # Texto com JSON embutido
        ('Aqui está o resultado da análise:\n{"verdict": "FALSO", "confidence_score": 0.88, "explanation": "Divergência de valores de R$ 500.", "sources": ["Portal Transparência"]}\nEspero ter ajudado.', "FALSO"),
        # Score em percentual inteiro (ex: 95 em vez de 0.95)
        ('{"verdict": "VERDADEIRO", "confidence_score": 95, "explanation": "Validado com R$ 1.000.", "sources": ["Câmara"]}', "VERDADEIRO"),
        # Veredito em minúsculas
        ('{"verdict": "inconclusivo", "confidence_score": 0.70, "explanation": "Dados insuficientes.", "sources": []}', "INCONCLUSIVO"),
        # Veredito inesperado/inválido -> deve sanitizar para INCONCLUSIVO
        ('{"verdict": "TALVEZ", "confidence_score": 0.50, "explanation": "Incerteza.", "sources": []}', "INCONCLUSIVO"),
        # JSON quebrado/truncado com regex fallback
        ('Texto do modelo {"verdict": "VERDADEIRO", "explanation": "Confirmado com R$ 20.000"} truncado...', "VERDADEIRO"),
        # Falha total de JSON
        ('Erro 500 do servidor de inferência. Não foi possível gerar JSON.', "INCONCLUSIVO"),
    ],
)
def test_resilience_against_various_json_formatting_anomalies(raw_llm_response: str, expected_verdict: str):
    """Valida que nenhuma anomalia de formatação ou texto da LLM causa crash ou quebra de contrato JSON."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = raw_llm_response

    state = {
        "claim": "Alegação de teste de robustez.",
        "evidences": [
            {
                "tool": "check_parliamentary_expenses",
                "status": "success",
                "data": {"valor_total": 1000.0, "qtd_lancamentos": 2},
            }
        ],
    }

    result = synthesizer_node(state, llm_client=mock_llm)

    # Veredito sanitizado
    assert result["verdict"] == expected_verdict
    # Tipagem sempre respeitada
    assert isinstance(result["confidence_score"], float)
    assert 0.0 <= result["confidence_score"] <= 1.0
    assert isinstance(result["explanation"], str) and len(result["explanation"]) > 0
    assert isinstance(result["sources"], list)
    # Serializável para JSON sem erros
    assert json.dumps(result) is not None


# ---------------------------------------------------------------------------
# 4. Cenários Integrados de Mocks de Ferramentas Oficiais
# ---------------------------------------------------------------------------

def test_mock_tool_pipeline_contradictory_numbers_yields_falso():
    """Valida síntese de mock onde as evidências numéricas contradizem frontalmente a alegação."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "verdict": "FALSO",
        "confidence_score": 0.96,
        "explanation": "O teto mensal de combustível pela cota parlamentar é de R$ 6.000,00, contradizendo o valor alegado de R$ 500,00.",
        "sources": ["Ato da Mesa da Câmara dos Deputados"],
    })

    # Simulação da Claim 13 do Golden Dataset
    state = {
        "claim": "Todo deputado federal tem um teto fixo de R$ 500,00 por ano para gastar com combustível pela cota parlamentar.",
        "evidences": [
            {
                "tool": "check_institutional_rule",
                "status": "success",
                "data": {
                    "topico": "teto_categoria_combustivel",
                    "teto_mensal": 6000.0,
                    "fonte_normativa": "Ato da Mesa da Câmara dos Deputados",
                    "resposta_resumida": "O limite mensal de reembolso de combustíveis é de R$ 6.000,00 e não R$ 500,00 anuais.",
                },
            }
        ],
    }

    result = synthesizer_node(state, llm_client=mock_llm)

    assert result["verdict"] == "FALSO"
    assert "6.000" in result["explanation"] or "6000" in result["explanation"]
    assert "500" in result["explanation"]
    assert "Ato da Mesa da Câmara dos Deputados" in result["sources"]


def test_mock_tool_network_timeout_yields_inconclusivo():
    """Valida que simulação de timeout ou falha de rede em todas as ferramentas resulta em INCONCLUSIVO."""
    mock_llm = MagicMock()

    state = {
        "claim": "O senador X votou contra a proposta de segurança pública.",
        "evidences": [
            {
                "tool": "get_proposition_vote_result",
                "status": "error",
                "error": "Timeout de conexão (HTTP 504 Gateway Timeout)",
                "data": None,
            }
        ],
    }

    result = synthesizer_node(state, llm_client=mock_llm)

    assert result["verdict"] == "INCONCLUSIVO"
    assert not mock_llm.generate.called
