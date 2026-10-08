"""Testes unitários para o Nó Agregador de Veredito da Matéria (Article Aggregator).

Atende aos critérios da Task 4.4:
- Módulo implementado em src/agents/nodes/article_aggregator.py.
- Regra de agregação de status do artigo (se contiver ao menos uma alegação falsa, classifica como ENGANOSO ou FALSO).
- Geração de resumo executivo em 2 a 3 parágrafos explicando os pontos confirmados e desmentidos.
- Inclusão de percentual de confiabilidade calculado com base na proporção das afirmações analisadas.
"""

from unittest.mock import MagicMock
import pytest

from src.agents.nodes.article_aggregator import (
    ArticleAggregationResult,
    ArticleAggregator,
    article_aggregator_node,
)


# ============================================================================
# 1. Testes de Regras de Agregação de Status e Confiabilidade
# ============================================================================

def test_article_aggregator_all_true_claims():
    """Valida agregação para artigo com 100% de alegações confirmadas como verdadeiras."""
    claims = [
        {
            "claim": "Deputado Pompeo de Mattos foi o maior gastador da CEAP em 2023.",
            "verdict": "VERDADEIRO",
            "explanation": "Dados oficiais da Câmara confirmam a liderança de gastos.",
            "sources": ["Câmara dos Deputados - CEAP"],
        },
        {
            "claim": "O Senado aprovou a PEC 45 da Reforma Tributária em 2023.",
            "verdict": "VERDADEIRO",
            "explanation": "Votação nominal aprovada em plenário no Senado.",
            "sources": ["Senado Federal"],
        },
    ]

    result = article_aggregator_node(claims=claims)

    assert isinstance(result, ArticleAggregationResult)
    assert result.overall_status == "VERDADEIRO"
    assert result.reliability_score == 100.0
    assert result.metrics["true_claims"] == 2
    assert result.metrics["false_claims"] == 0
    assert len(result.confirmed_points) == 2
    assert len(result.refuted_points) == 0


def test_article_aggregator_mixed_claims_with_false_is_enganoso():
    """Valida que ao menos uma alegação falsa relevante classifica o artigo como ENGANOSO."""
    claims = [
        {
            "claim": "Deputados podem pedir reembolso de alimentação pela cota.",
            "verdict": "VERDADEIRO",
            "explanation": "Permitido pelo Ato da Mesa da Câmara.",
            "sources": ["Câmara dos Deputados"],
        },
        {
            "claim": "O deputado comprou um imóvel em seu próprio nome com a cota parlamentar.",
            "verdict": "FALSO",
            "explanation": "A norma veda estritamente a aquisição de bens permanentes ou imóveis.",
            "sources": ["Regimento Interno e Ato da Mesa"],
        },
    ]

    result = article_aggregator_node(claims=claims)

    assert result.overall_status == "ENGANOSO"
    # 1 de 2 é verdadeira -> 50.0%
    assert result.reliability_score == 50.0
    assert result.metrics["true_claims"] == 1
    assert result.metrics["false_claims"] == 1
    assert len(result.confirmed_points) == 1
    assert len(result.refuted_points) == 1


def test_article_aggregator_all_false_claims_is_falso():
    """Valida que quando todas as alegações checadas forem falsas, o artigo é classificado como FALSO."""
    claims = [
        {
            "claim": "Todo deputado tem teto fixo de R$ 500 por ano para combustível.",
            "verdict": "FALSO",
            "explanation": "O teto mensal é de R$ 6.000 e não de R$ 500 anuais.",
            "sources": ["Ato da Mesa da Câmara"],
        },
        {
            "claim": "O Senado proibiu totalmente o uso da cota para passagens aéreas.",
            "verdict": "FALSO",
            "explanation": "Passagens aéreas continuam sendo despesa expressamente indenizável.",
            "sources": ["Senado Federal - CEAPS"],
        },
    ]

    result = article_aggregator_node(claims=claims)

    assert result.overall_status == "FALSO"
    assert result.reliability_score == 0.0
    assert result.metrics["false_claims"] == 2
    assert len(result.refuted_points) == 2
    assert len(result.confirmed_points) == 0


def test_article_aggregator_only_inconclusive_claims():
    """Valida artigo onde todas as alegações resultaram em inconclusivo."""
    claims = [
        {
            "claim": "Um parlamentar teria gastado muito dinheiro no ano passado.",
            "verdict": "INCONCLUSIVO",
            "explanation": "Alegação subespecificada sem nome ou valores ancoráveis.",
            "sources": ["Constituição do Agente"],
        }
    ]

    result = article_aggregator_node(claims=claims)

    assert result.overall_status == "INCONCLUSIVO"
    assert result.metrics["inconclusive_claims"] == 1
    assert len(result.inconclusive_points) == 1


def test_article_aggregator_empty_claims_safe():
    """Valida que lista vazia de afirmações não quebra e retorna status INCONCLUSIVO seguro."""
    result = article_aggregator_node(claims=[])

    assert result.overall_status == "INCONCLUSIVO"
    assert result.reliability_score == 0.0
    assert result.metrics["total_claims"] == 0
    assert "nenhuma alegação" in result.executive_summary.lower()


# ============================================================================
# 2. Testes da Geração do Resumo Executivo (2 a 3 Parágrafos)
# ============================================================================

def test_article_aggregator_executive_summary_structure():
    """Valida que o resumo executivo contém entre 2 e 3 parágrafos bem delimitados."""
    claims = [
        {
            "claim": "PEC 45 foi aprovada no Senado.",
            "verdict": "VERDADEIRO",
            "explanation": "Votação oficial confirmada.",
            "sources": ["Senado Federal"],
        },
        {
            "claim": "Deputado comprou imóvel com cota.",
            "verdict": "FALSO",
            "explanation": "Compra de imóvel é proibida.",
            "sources": ["Câmara dos Deputados"],
        },
    ]

    result = article_aggregator_node(claims=claims, article_title="Notícia sobre votações e despesas")

    # Parágrafos são separados por quebras duplas de linha
    paragraphs = [p.strip() for p in result.executive_summary.split("\n\n") if p.strip()]

    assert 2 <= len(paragraphs) <= 3
    # Primeiro parágrafo: visão geral da matéria e classificação
    assert "notícia" in paragraphs[0].lower() or "artigo" in paragraphs[0].lower() or "análise" in paragraphs[0].lower()
    # Menções aos pontos confirmados e desmentidos
    full_text = result.executive_summary.lower()
    assert "confirm" in full_text
    assert "desment" in full_text or "fals" in full_text or "incorret" in full_text


def test_article_aggregator_with_llm_synthesis():
    """Valida que o componente pode sintetizar o resumo via LLM quando fornecido."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = (
        "A matéria jornalística em análise apresenta um grau misto de confiabilidade factual.\n\n"
        "Entre os pontos confirmados oficialmente, verificou-se que a PEC 45 foi aprovada no Senado em 2023.\n\n"
        "Em contrapartida, foi desmentida a afirmação sobre a compra de imóvel usando a cota parlamentar, caracterizando o artigo como enganoso."
    )

    aggregator = ArticleAggregator(llm_client=mock_llm)
    claims = [
        {"claim": "PEC 45 aprovada", "verdict": "VERDADEIRO"},
        {"claim": "Compra de imóvel na cota", "verdict": "FALSO"},
    ]

    result = aggregator.aggregate(claims=claims)

    assert mock_llm.generate.called
    paragraphs = [p for p in result.executive_summary.split("\n\n") if p.strip()]
    assert len(paragraphs) == 3
    assert result.overall_status == "ENGANOSO"


def test_article_aggregator_deterministic_fallback_on_llm_error():
    """Valida que falhas no LLM não quebram a agregação e ativam fallback determinístico de 2 a 3 parágrafos."""
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = RuntimeError("Erro de conexão no modelo")

    aggregator = ArticleAggregator(llm_client=mock_llm)
    claims = [
        {"claim": "Fato real comprovado", "verdict": "VERDADEIRO"},
        {"claim": "Boato desmentido", "verdict": "FALSO"},
    ]

    result = aggregator.aggregate(claims=claims)

    assert isinstance(result, ArticleAggregationResult)
    paragraphs = [p for p in result.executive_summary.split("\n\n") if p.strip()]
    assert 2 <= len(paragraphs) <= 3
    assert result.overall_status == "ENGANOSO"


# ============================================================================
# 3. Testes de Suporte a Dicionário de Estado
# ============================================================================

def test_article_aggregator_node_dict_state_enrichment():
    """Valida enriquecimento direto de dicionário de estado para pipelines de agentes."""
    state = {
        "url": "https://noticia.com/fato",
        "title": "Manchete Política",
        "claims": [
            {"claim": "Fato 1", "verdict": "VERDADEIRO"},
            {"claim": "Fato 2", "verdict": "VERDADEIRO"},
        ],
    }

    result = article_aggregator_node(state=state)

    assert result.overall_status == "VERDADEIRO"
    assert "article_aggregation" in state
    assert state["article_aggregation"] == result.model_dump()
