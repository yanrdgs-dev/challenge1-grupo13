"""Testes unitários para o Nó Extrator de Alegações Atômicas (Claim Extractor).

Atende aos critérios da Task 4.2:
- Implementação do nó claim_extractor_node em src/agents/nodes/claim_extractor.py.
- Prompt com diretrizes estritas para selecionar apenas alegações verificáveis contra dados públicos.
- Saída obrigatoriamente compatível com o schema list[AtomicClaim] contendo no máximo 5 itens.
- Casos onde a notícia não possui alegações verificáveis retornando lista vazia sem quebrar o fluxo.
"""

import json
from unittest.mock import MagicMock

import pytest

from src.agents.nodes.claim_extractor import (
    CLAIM_EXTRACTOR_SYSTEM_PROMPT,
    ClaimExtractor,
    claim_extractor_node,
)
from src.schemas.claims import AtomicClaim


# ============================================================================
# 1. Testes do Schema AtomicClaim
# ============================================================================

def test_atomic_claim_schema_instantiation_and_fields():
    """Valida a instanciação do schema AtomicClaim e acesso aos seus atributos."""
    claim = AtomicClaim(
        claim="Em 2023, o deputado Pompeo de Mattos foi o maior gastador da CEAP na Câmara.",
        category="GASTOS",
        target_entity="Pompeo de Mattos",
        context="Reportagem aponta que gastos somaram valor expressivo na cota.",
        verifiable=True,
    )

    assert claim.claim == "Em 2023, o deputado Pompeo de Mattos foi o maior gastador da CEAP na Câmara."
    assert claim.text == claim.claim
    assert claim["claim"] == claim.claim
    assert claim.category == "GASTOS"
    assert claim.target_entity == "Pompeo de Mattos"
    assert claim.verifiable is True

    dumped = claim.model_dump()
    assert isinstance(dumped, dict)
    assert dumped["claim"] == claim.claim
    assert dumped["category"] == "GASTOS"


def test_atomic_claim_resilience_inputs():
    """Valida flexibilidade na criação de AtomicClaim via string simples ou alias 'text'."""
    claim_str = AtomicClaim("Senado aprovou a PEC 45 em 2023.")
    assert claim_str.claim == "Senado aprovou a PEC 45 em 2023."
    assert claim_str.text == "Senado aprovou a PEC 45 em 2023."

    claim_alias = AtomicClaim(text="Deputado gastou R$ 10.000 em passagens.")
    assert claim_alias.claim == "Deputado gastou R$ 10.000 em passagens."


# ============================================================================
# 2. Testes do Caminho Feliz e Extração
# ============================================================================

def test_claim_extractor_node_happy_path():
    """Valida caminho feliz: texto de notícia com fatos verificáveis retorna list[AtomicClaim]."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "claims": [
            {
                "claim": "O deputado federal Pompeo de Mattos foi o parlamentar que mais gastou a cota parlamentar (CEAP) em 2023.",
                "category": "GASTOS",
                "target_entity": "Pompeo de Mattos",
                "context": "Pompeo de Mattos liderou os gastos da cota na Câmara.",
            },
            {
                "claim": "O Senado aprovou a PEC da Reforma Tributária em 2023.",
                "category": "VOTACOES",
                "target_entity": "Senado Federal",
                "context": "Votação no Plenário do Senado sacramentou a aprovação.",
            },
        ]
    })

    news_text = (
        "Brasília - Levantamento aponta que o deputado Pompeo de Mattos liderou "
        "os gastos da cota na Câmara em 2023. No mesmo ano, o Senado aprovou a PEC da Reforma Tributária."
    )

    claims = claim_extractor_node(news_text, llm_client=mock_llm)

    assert isinstance(claims, list)
    assert len(claims) == 2
    for c in claims:
        assert isinstance(c, AtomicClaim)

    assert claims[0].category == "GASTOS"
    assert "Pompeo de Mattos" in claims[0].claim
    assert claims[1].category == "VOTACOES"
    assert "PEC da Reforma Tributária" in claims[1].claim

    # Valida que o LLM foi chamado com o texto e as diretrizes do sistema
    prompt_sent = mock_llm.generate.call_args[0][0]
    assert news_text in prompt_sent
    assert "gastos" in prompt_sent.lower()
    assert "votações" in prompt_sent.lower() or "votacoes" in prompt_sent.lower()


def test_claim_extractor_node_caps_at_maximum_5_claims():
    """Valida que o nó restringe obrigatoriamente a saída a no máximo 5 itens."""
    mock_llm = MagicMock()
    # Simula resposta do LLM com 8 alegações
    mock_llm.generate.return_value = json.dumps({
        "claims": [
            {"claim": f"Afirmação factual número {i}", "category": "GASTOS"}
            for i in range(1, 9)
        ]
    })

    text = "Notícia contendo múltiplas alegações sobre despesas e votos."
    claims = claim_extractor_node(text, llm_client=mock_llm)

    assert isinstance(claims, list)
    assert len(claims) == 5
    assert claims[0].claim == "Afirmação factual número 1"
    assert claims[4].claim == "Afirmação factual número 5"


# ============================================================================
# 3. Testes de Casos Sem Alegações Verificáveis / Filtragem
# ============================================================================

def test_claim_extractor_node_pure_opinion_returns_empty_list():
    """Valida que textos opinativos/editoriais sem fatos verificáveis retornam lista vazia."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({"claims": []})

    opinion_text = (
        "Editorial: O cenário político atual é lamentável. A postura dos líderes "
        "revela mediocridade e falta de comprometimento com o futuro da nação. "
        "O eleitor precisa acordar e exigir mais seriedade."
    )

    claims = claim_extractor_node(opinion_text, llm_client=mock_llm)

    assert isinstance(claims, list)
    assert len(claims) == 0
    assert claims == []


def test_claim_extractor_node_empty_or_whitespace_input():
    """Valida que textos vazios, None ou apenas espaços retornam lista vazia sem chamar LLM."""
    mock_llm = MagicMock()

    assert claim_extractor_node("", llm_client=mock_llm) == []
    assert claim_extractor_node("   \n\t   ", llm_client=mock_llm) == []
    assert claim_extractor_node(None, llm_client=mock_llm) == []
    assert mock_llm.generate.call_count == 0


def test_claim_extractor_node_filters_rhetoric_and_keeps_facts():
    """Valida filtragem de adjetivações retóricas mantendo apenas a afirmação factual."""
    mock_llm = MagicMock()
    # O LLM (conforme instruído no prompt) filtra o discurso de ódio e mantém apenas o fato
    mock_llm.generate.return_value = json.dumps({
        "claims": [
            {
                "claim": "O deputado gastou R$ 50.000 em passagens aéreas em 2023.",
                "category": "GASTOS",
                "target_entity": "Deputado",
                "context": "gastou R$ 50.000 em passagens aéreas em 2023",
            }
        ]
    })

    text_with_rhetoric = (
        "Em um ato vergonhoso e ultrajante que revoltou toda a população de bem, "
        "o deputado gastou R$ 50.000 em passagens aéreas em 2023. É um escândalo inaceitável!"
    )

    claims = claim_extractor_node(text_with_rhetoric, llm_client=mock_llm)

    assert len(claims) == 1
    assert "gastou R$ 50.000 em passagens aéreas" in claims[0].claim
    assert "vergonhoso" not in claims[0].claim.lower()


# ============================================================================
# 4. Testes de Suporte a Estado / Dicionário (Integração com Pipelines)
# ============================================================================

def test_claim_extractor_node_with_dict_state_input():
    """Valida que o nó aceita dicionário de estado contendo clean_text (saída do url_scraper)."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "claims": [
            {"claim": "Deputado gastou na cota parlamentar", "category": "GASTOS"}
        ]
    })

    state = {
        "url": "https://g1.globo.com/politica/noticia/2023/10/gastos.ghtml",
        "title": "Gastos da cota parlamentar em 2023",
        "clean_text": "O deputado realizou despesas com a cota parlamentar.",
    }

    claims = claim_extractor_node(state, llm_client=mock_llm)

    assert isinstance(claims, list)
    assert len(claims) == 1
    assert isinstance(claims[0], AtomicClaim)
    # Verifica que o estado foi enriquecido sem quebrar o retorno
    assert "atomic_claims" in state
    assert state["atomic_claims"] == claims


def test_claim_extractor_node_with_alternative_dict_keys():
    """Valida suporte a outras chaves comuns como 'text' e 'content'."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "claims": [{"claim": "Votação ocorreu no Plenário", "category": "VOTACOES"}]
    })

    claims1 = claim_extractor_node({"text": "Texto com voto."}, llm_client=mock_llm)
    assert len(claims1) == 1

    claims2 = claim_extractor_node({"content": "Conteúdo com voto."}, llm_client=mock_llm)
    assert len(claims2) == 1


# ============================================================================
# 5. Robustez e Resiliência na Resposta do LLM
# ============================================================================

def test_claim_extractor_node_markdown_json_wrapping():
    """Valida que blocos de código markdown (```json ... ```) são tratados corretamente."""
    mock_llm = MagicMock()
    markdown_response = (
        "Aqui estão as alegações extraídas da matéria:\n\n"
        "```json\n"
        "{\n"
        '  "claims": [\n'
        '    {"claim": "Deputado X votou SIM na PEC 45", "category": "VOTACOES"}\n'
        "  ]\n"
        "}\n"
        "```\n\n"
        "Fim da extração."
    )
    mock_llm.generate.return_value = markdown_response

    claims = claim_extractor_node("Notícia de teste", llm_client=mock_llm)

    assert len(claims) == 1
    assert claims[0].claim == "Deputado X votou SIM na PEC 45"
    assert claims[0].category == "VOTACOES"


def test_claim_extractor_node_malformed_json_fallback_safe():
    """Valida que resposta corrompida do LLM não quebra o fluxo e retorna lista vazia."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "Erro interno: não consegui processar o pedido como JSON."

    claims = claim_extractor_node("Notícia de teste", llm_client=mock_llm)

    assert isinstance(claims, list)
    assert claims == []


def test_claim_extractor_node_llm_exception_resilience():
    """Valida que falha/timeout na chamada do LLM não interrompe a aplicação e retorna lista vazia."""
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = RuntimeError("Falha total na conexão com o LLM")

    claims = claim_extractor_node("Notícia de teste", llm_client=mock_llm)

    assert isinstance(claims, list)
    assert claims == []


# ============================================================================
# 6. Validação das Diretrizes Estritas do Prompt
# ============================================================================

def test_claim_extractor_prompt_contains_strict_guidelines():
    """Valida que o prompt contém instruções estritas sobre dados públicos e filtragem."""
    prompt = CLAIM_EXTRACTOR_SYSTEM_PROMPT.lower()

    # Requisitos de dados públicos
    assert "gastos" in prompt
    assert "votações" in prompt or "votacoes" in prompt
    assert "públicos" in prompt or "publicos" in prompt

    # Requisitos de filtragem
    assert "opiniões" in prompt or "opinioes" in prompt
    assert "adjetivações" in prompt or "adjetivacoes" in prompt or "retórica" in prompt or "retorica" in prompt

    # Requisitos de formato e limite
    assert "5" in prompt
    assert "json" in prompt


# ============================================================================
# 7. Teste de Uso Direto da Classe ClaimExtractor
# ============================================================================

def test_claim_extractor_class_direct_usage():
    """Valida que a classe ClaimExtractor pode ser utilizada de forma desacoplada."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "claims": [{"claim": "Alegação de teste direto", "category": "OUTRO"}]
    })

    extractor = ClaimExtractor(llm_client=mock_llm, max_claims=3)
    results = extractor.extract("Texto de teste para classe")

    assert len(results) == 1
    assert results[0].claim == "Alegação de teste direto"
