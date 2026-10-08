"""Testes unitários e de integração para o Endpoint POST /api/v1/verify-url.

Atende aos critérios da Task 4.3:
- Endpoint POST /api/v1/verify-url criado e exposto na API.
- Payload de entrada recebendo {"url": "https://..."}.
- Encadeamento completo: Ingestão da URL -> Extração de Claims -> Execução do Grafo de Verificação em Lote.
- Tempo de resposta monitorado e controlado para não ultrapassar limites de timeout de rede do cliente.
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.schemas.claims import AtomicClaim

client = TestClient(app)


# ============================================================================
# 1. Testes do Encadeamento Completo (Happy Path)
# ============================================================================

@patch("src.api.routes.verify_url.extract_article")
@patch("src.api.routes.verify_url.claim_extractor_node")
@patch("src.api.routes.verify_url.get_pipeline")
def test_verify_url_success_full_chain(mock_get_pipeline, mock_claim_extractor, mock_extract_article):
    """Valida encadeamento completo: Ingestão -> Extração -> Grafo de Verificação em Lote."""
    # 1. Mock da ingestão da notícia via URL
    mock_extract_article.return_value = {
        "success": True,
        "url": "https://g1.globo.com/politica/noticia/2023/10/gastos-parlamentares.ghtml",
        "title": "Levantamento aponta gastos na Câmara e aprovação de PEC",
        "author": "Equipe de Política",
        "publish_date": "2023-10-15",
        "clean_text": "Texto completo do artigo jornalístico extraído com sucesso.",
    }

    # 2. Mock do extrator de claims atômicas
    claims = [
        AtomicClaim(
            claim="O deputado Pompeo de Mattos foi o maior gastador da CEAP em 2023.",
            category="GASTOS",
            target_entity="Pompeo de Mattos",
        ),
        AtomicClaim(
            claim="O Senado aprovou a PEC da Reforma Tributária em 2023.",
            category="VOTACOES",
            target_entity="Senado Federal",
        ),
    ]
    mock_claim_extractor.return_value = claims

    # 3. Mock da execução do pipeline multiagente em lote
    mock_pipeline = MagicMock()
    mock_pipeline.verify.side_effect = [
        {
            "claim": "O deputado Pompeo de Mattos foi o maior gastador da CEAP em 2023.",
            "verdict": "VERDADEIRO",
            "confidence": "ALTA",
            "explanation": "Registros oficiais da CEAP confirmam Pompeo de Mattos na liderança.",
            "sources_cited": ["Câmara dos Deputados - CEAP"],
            "plan": {"reasoning": "Consulta aos dados abertos de despesas"},
            "latency_seconds": {"total": 0.5},
        },
        {
            "claim": "O Senado aprovou a PEC da Reforma Tributária em 2023.",
            "verdict": "VERDADEIRO",
            "confidence": "ALTA",
            "explanation": "A votação nominal da PEC 45/2019 foi aprovada no plenário.",
            "sources_cited": ["Senado Federal - Dados Abertos"],
            "plan": {"reasoning": "Consulta à API de votações"},
            "latency_seconds": {"total": 0.4},
        },
    ]
    mock_get_pipeline.return_value = mock_pipeline

    response = client.post(
        "/api/v1/verify-url",
        json={"url": "https://g1.globo.com/politica/noticia/2023/10/gastos-parlamentares.ghtml"},
    )

    assert response.status_code == 200
    data = response.json()

    # Valida payload de retorno
    assert data["url"] == "https://g1.globo.com/politica/noticia/2023/10/gastos-parlamentares.ghtml"
    assert data["success"] is True
    assert data["article"]["title"] == "Levantamento aponta gastos na Câmara e aprovação de PEC"
    assert data["article"]["author"] == "Equipe de Política"
    assert data["claims_count"] == 2
    assert len(data["claims"]) == 2

    # Valida resultados individuais em lote
    assert data["claims"][0]["claim"] == "O deputado Pompeo de Mattos foi o maior gastador da CEAP em 2023."
    assert data["claims"][0]["verdict"] == "VERDADEIRO"
    assert data["claims"][1]["verdict"] == "VERDADEIRO"
    assert data["overall_verdict"] == "VERDADEIRO"

    # Valida monitoramento de latência
    assert "latency_seconds" in data
    assert "scraping" in data["latency_seconds"]
    assert "claim_extraction" in data["latency_seconds"]
    assert "batch_verification" in data["latency_seconds"]
    assert "total" in data["latency_seconds"]
    assert data["timeout_exceeded"] is False


# ============================================================================
# 2. Testes de Validação do Payload de Entrada
# ============================================================================

def test_verify_url_invalid_urls_return_400():
    """Valida rejeição com 400 Bad Request para URLs inválidas ou sem protocolo."""
    # URL vazia
    res_empty = client.post("/api/v1/verify-url", json={"url": "   "})
    assert res_empty.status_code == 400
    assert "inválida" in res_empty.json()["detail"].lower()

    # URL sem esquema HTTP/HTTPS
    res_no_proto = client.post("/api/v1/verify-url", json={"url": "noticia_sem_url"})
    assert res_no_proto.status_code == 400

    # Payload sem o campo 'url'
    res_missing = client.post("/api/v1/verify-url", json={})
    assert res_missing.status_code == 422


# ============================================================================
# 3. Testes de Tratamento de Erros de Ingestão / Scraping
# ============================================================================

@patch("src.api.routes.verify_url.extract_article")
def test_verify_url_scraping_failure_handling(mock_extract_article):
    """Valida tratamento seguro quando a extração da URL falha (404, DNS ou Paywall)."""
    mock_extract_article.return_value = {
        "success": False,
        "error_type": "HTTP_ERROR_404",
        "message": "Página não encontrada no servidor remoto.",
        "clean_text": "",
        "url": "https://site-inexistente.com/404",
    }

    response = client.post(
        "/api/v1/verify-url",
        json={"url": "https://site-inexistente.com/404"},
    )

    assert response.status_code == 400
    data = response.json()
    assert "Página não encontrada" in data["detail"]


# ============================================================================
# 4. Testes de Notícia Sem Alegações Verificáveis
# ============================================================================

@patch("src.api.routes.verify_url.extract_article")
@patch("src.api.routes.verify_url.claim_extractor_node")
@patch("src.api.routes.verify_url.get_pipeline")
def test_verify_url_no_claims_returns_inconclusive(mock_get_pipeline, mock_claim_extractor, mock_extract_article):
    """Valida retorno amigável com veredito INCONCLUSIVO quando a matéria não possui claims factuais."""
    mock_extract_article.return_value = {
        "success": True,
        "url": "https://site.com/opiniao",
        "title": "Editorial sobre o clima político",
        "author": "Colunista",
        "publish_date": "2023-10-10",
        "clean_text": "Texto puramente opinativo e sem alegações factuais checáveis.",
    }

    # Nó extrator retorna lista vazia
    mock_claim_extractor.return_value = []

    response = client.post(
        "/api/v1/verify-url",
        json={"url": "https://site.com/opiniao"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["claims_count"] == 0
    assert data["claims"] == []
    assert data["overall_verdict"] == "INCONCLUSIVO"
    assert "nenhuma alegação" in data["message"].lower()

    # O pipeline não deve ser invocado se não houver alegações
    assert not mock_get_pipeline.called


# ============================================================================
# 5. Testes de Controle de Limite de Tempo / Timeout Budget
# ============================================================================

@patch("src.api.routes.verify_url.extract_article")
@patch("src.api.routes.verify_url.claim_extractor_node")
@patch("src.api.routes.verify_url.get_pipeline")
@patch("src.api.routes.verify_url.time.perf_counter")
def test_verify_url_timeout_budget_control(mock_perf_counter, mock_get_pipeline, mock_claim_extractor, mock_extract_article):
    """Valida que o loop em lote interrompe a verificação se o tempo restante estiver se esgotando."""
    mock_extract_article.return_value = {
        "success": True,
        "url": "https://site.com/noticia-longa",
        "title": "Muitas Alegações",
        "author": "Jornalista",
        "publish_date": "2023-10-10",
        "clean_text": "Notícia extensa...",
    }

    mock_claim_extractor.return_value = [
        AtomicClaim(claim=f"Alegação factual número {i}") for i in range(1, 5)
    ]

    mock_pipeline = MagicMock()
    mock_pipeline.verify.return_value = {
        "claim": "Alegação factual número 1",
        "verdict": "VERDADEIRO",
        "confidence": "ALTA",
        "explanation": "OK",
        "sources_cited": [],
        "plan": {},
        "latency_seconds": {"total": 0.2},
    }
    mock_get_pipeline.return_value = mock_pipeline

    call_count = 0

    def get_time():
        nonlocal call_count
        call_count += 1
        # Primeiras chamadas: tempo inicial estável (1.0s)
        # Quando a 1ª claim é concluída e o loop vai para a 2ª: tempo avança para 29.0s (estouro)
        if call_count <= 8:
            return 1.0
        return 29.0

    mock_perf_counter.side_effect = get_time

    response = client.post(
        "/api/v1/verify-url",
        json={"url": "https://site.com/noticia-longa"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["timeout_exceeded"] is True
    # Apenas a 1ª claim foi executada antes da interrupção defensiva
    assert len(data["claims"]) == 1
    assert data["claims"][0]["claim"] == "Alegação factual número 1"
