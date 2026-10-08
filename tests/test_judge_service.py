"""Testes do Judge Service com LLMClient mockado."""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.core.llm_client import ChatResult
from src.services import judge_service
from src.services.judge_service import app

client = TestClient(app)

PAYLOAD = {"claim": "Fulano é do PL-SP.", "evidence": {"partido": "PL"}, "tool_used": "resolve_politician"}


def _result(content):
    return ChatResult(
        content=content,
        usage={"input_tokens": 50, "output_tokens": 20},
        provider="ollama",
        model="qwen2.5:14b",
    )


@pytest.fixture
def mock_llm():
    with patch.object(judge_service, "llm_client") as m:
        yield m


def test_judge_happy_path(mock_llm):
    mock_llm.chat.return_value = _result(json.dumps({
        "veredito": "verdadeiro",
        "confianca": "ALTA",
        "justificativa": "Confirmado.",
        "fontes_primarias": ["Câmara dos Deputados"],
    }))
    resp = client.post("/judge", json=PAYLOAD)

    assert resp.status_code == 200
    data = resp.json()
    assert data["veredito"] == "VERDADEIRO"
    assert data["fontes_primarias"] == ["Câmara dos Deputados"]
    kwargs = mock_llm.chat.call_args.kwargs
    assert kwargs["json_mode"] is True
    assert kwargs["model"] == judge_service.JUDGE_MODEL


def test_judge_invalid_verdict_becomes_inconclusive(mock_llm):
    mock_llm.chat.return_value = _result(json.dumps({"veredito": "TALVEZ"}))
    assert client.post("/judge", json=PAYLOAD).json()["veredito"] == "INCONCLUSIVO"


def test_judge_non_json_becomes_inconclusive(mock_llm):
    mock_llm.chat.return_value = _result("isso não é json")
    data = client.post("/judge", json=PAYLOAD).json()
    assert data["veredito"] == "INCONCLUSIVO"
    assert data["confianca"] == "BAIXA"


def test_judge_llm_failure_returns_503(mock_llm):
    mock_llm.chat.side_effect = RuntimeError("Falha total")
    assert client.post("/judge", json=PAYLOAD).status_code == 503
