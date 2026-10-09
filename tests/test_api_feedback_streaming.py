"""Testes TDD para endpoints de feedback e streaming da API de Fact-Checking."""

import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_post_positive_feedback():
    """Valida registro com sucesso de avaliação positiva para uma checagem."""
    payload = {
        "message_id": "chk-12345",
        "query": "A confirmação de ministros do STF é por votação secreta?",
        "verdict": "VERDADEIRO",
        "rating": "positive",
        "comment": "Evidência muito clara da CF/88.",
    }
    response = client.post("/api/feedback", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "feedback_id" in data


def test_post_negative_feedback_with_reason():
    """Valida registro de avaliação negativa com motivo estruturado."""
    payload = {
        "message_id": "chk-67890",
        "query": "Deputado gastou x reais",
        "verdict": "INCONCLUSIVO",
        "rating": "negative",
        "reason": "Veredito equivocado",
        "comment": "Deveria ter consultado a prestação de contas do TSE.",
    }
    response = client.post("/api/feedback", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_post_invalid_feedback_rating():
    """Valida rejeição de feedback com rating inválido."""
    payload = {
        "message_id": "chk-99999",
        "rating": "invalido",
    }
    response = client.post("/api/feedback", json=payload)
    assert response.status_code == 422


def test_check_claim_stream_sse():
    """Valida que o endpoint de streaming emite eventos SSE para as etapas e resposta."""
    mock_pipeline = MagicMock()
    mock_pipeline.verify.return_value = {
        "verdict": "VERDADEIRO",
        "explanation": "A votação é secreta conforme o Art. 52 da CF.",
        "confidence": "ALTA",
        "latency_seconds": {"orchestrator": 0.1, "tools": 0.2, "synthesizer": 0.3, "total": 0.6},
        "plan": {"reasoning": "Regra institucional"},
        "evidences": [{"tool": "check_institutional_rule", "data": {"fonte_normativa": "CF/88"}}],
        "sources_cited": ["CF/88"],
    }

    with patch("src.api.routes.factcheck.get_pipeline", return_value=mock_pipeline):
        response = client.post("/api/check/stream", json={"query": "A votação de ministro do STF é secreta?"})
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        
        # Lê o corpo do streaming
        content = response.text
        assert "event: step" in content
        assert "tools" in content or "Definindo ferramentas" in content
        assert "event: done" in content or "complete" in content
