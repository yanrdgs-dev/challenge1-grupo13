"""Testes automatizados para a API HTTP do Agente de Fact-Checking."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_health_check():
    """Valida que o endpoint de saúde responde 200 OK com metadados do sistema."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "tools_available" in data


def test_get_suggestions():
    """Valida o catálogo de sugestões para alimentar a interface."""
    response = client.get("/api/suggestions")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 4
    for item in data:
        assert "icon" in item
        assert "eyebrow" in item
        assert "text" in item


def test_check_claim_sabatina_stf_verdadeiro():
    """Valida checagem da Claim 10 (Sabatina STF) resultando em VERDADEIRO com evidência normativa."""
    payload = {"query": "A confirmação de ministros do STF pelo plenário do Senado é feita por votação secreta?"}
    response = client.post("/api/check", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["verdict"] == "VERDADEIRO"
    assert "Constituição Federal" in " ".join(data["sources"])
    assert len(data["text"]) > 0


def test_check_claim_combustivel_falso():
    """Valida checagem da Claim 13 (Teto Combustível) resultando em FALSO com evidência de ato da mesa."""
    payload = {"query": "Todo deputado federal tem um teto fixo de R$ 500 por ano para gastar com combustível pela cota?"}
    response = client.post("/api/check", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["verdict"] == "FALSO"
    assert any("Ato da Mesa" in src for src in data["sources"])


def test_check_claim_subespecificada_inconclusivo():
    """Valida Regra 3 da Constituição: alegações vagas/sem âncora retornam INCONCLUSIVO."""
    payload = {"query": "Nas redes sociais estão dizendo que um deputado gastou muito dinheiro recentemente."}
    response = client.post("/api/check", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["verdict"] == "INCONCLUSIVO"
    assert "subespecificada" in data["text"].lower() or "entidade" in data["text"].lower() or "inconclusivo" in data["text"].lower()


def test_check_empty_query_returns_422_or_400():
    """Valida tratamento seguro contra envio de consultas vazias."""
    response = client.post("/api/check", json={"query": "   "})
    assert response.status_code in (400, 422)
