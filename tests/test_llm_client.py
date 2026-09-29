"""Testes unitários e de integração para o módulo LLMClient."""

import pytest
import httpx
from unittest.mock import patch, MagicMock
from src.core.llm_client import LLMClient


def test_init_defaults():
    """Valida a inicialização padrão a partir do .env."""
    client = LLMClient()
    assert client.primary_provider == "ollama"
    assert client.fallback_provider == "groq"
    assert client.timeout == 3.0


def test_init_custom_params():
    """Valida a inicialização com parâmetros explícitos."""
    client = LLMClient(
        primary_provider="openai",
        fallback_provider="ollama",
        timeout=5.5,
    )
    assert client.primary_provider == "openai"
    assert client.fallback_provider == "ollama"
    assert client.timeout == 5.5


def test_generate_empty_prompt_raises_value_error():
    """Valida rejeição de prompt vazio ou inválido."""
    client = LLMClient()
    with pytest.raises(ValueError, match="O prompt deve ser uma string não vazia"):
        client.generate("")


def test_call_ollama_success():
    """Testa chamada bem-sucedida ao Ollama."""
    client = LLMClient(primary_provider="ollama")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": "Resposta do LLaMA"}

    with patch("httpx.Client.post", return_value=mock_response) as mock_post:
        result = client.generate("Olá")
        assert result == "Resposta do LLaMA"
        assert mock_post.called
        assert "/api/generate" in mock_post.call_args[0][0]


def test_fallback_to_groq_on_ollama_failure(monkeypatch):
    """Testa fallback automático para Groq quando Ollama falha."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_mock_key")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.1-8b-instant")

    client = LLMClient(primary_provider="ollama", fallback_provider="groq")

    def mock_post(url, *args, **kwargs):
        if "localhost" in url:
            # Simula falha de conexão ou timeout no Ollama local
            raise httpx.ConnectError("Connection refused by Ollama")
        elif "groq.com" in url:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": "Resposta da nuvem Groq"}}]
            }
            return resp
        raise ValueError(f"URL inesperada: {url}")

    with patch("httpx.Client.post", side_effect=mock_post):
        result = client.generate("Teste de fallback")
        assert result == "Resposta da nuvem Groq"


def test_fallback_to_openai_on_ollama_failure(monkeypatch):
    """Testa fallback automático para OpenAI quando Ollama falha."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")

    client = LLMClient(primary_provider="ollama", fallback_provider="openai")

    def mock_post(url, *args, **kwargs):
        if "localhost" in url:
            raise httpx.TimeoutException("Timeout no Ollama")
        elif "openai.com" in url:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": "Resposta da nuvem OpenAI"}}]
            }
            return resp
        raise ValueError(f"URL inesperada: {url}")

    with patch("httpx.Client.post", side_effect=mock_post):
        result = client.generate("Teste OpenAI")
        assert result == "Resposta da nuvem OpenAI"


def test_total_failure_raises_runtime_error(monkeypatch):
    """Testa lançamento de RuntimeError quando ambos os provedores falham."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_mock_key")
    client = LLMClient(primary_provider="ollama", fallback_provider="groq")

    with patch("httpx.Client.post", side_effect=httpx.ConnectError("Rede indisponível")):
        with pytest.raises(RuntimeError, match="Falha total nos serviços de LLM"):
            client.generate("Teste falha total")


def test_unknown_provider_raises_error():
    """Valida erro ao configurar provedor inexistente."""
    client = LLMClient(primary_provider="inexistente", fallback_provider=None)
    with pytest.raises(RuntimeError, match="Provedor desconhecido: 'inexistente'"):
        client.generate("Teste")


def test_groq_missing_api_key_raises_value_error(monkeypatch):
    """Valida que chamar Groq sem API key válida levanta erro explicativo."""
    monkeypatch.setenv("GROQ_API_KEY", "")
    client = LLMClient(primary_provider="groq", fallback_provider=None)

    with pytest.raises(RuntimeError, match="GROQ_API_KEY não configurada"):
        client.generate("Teste")


def test_openai_missing_api_key_raises_value_error(monkeypatch):
    """Valida que chamar OpenAI sem API key válida levanta erro explicativo."""
    monkeypatch.setenv("OPENAI_API_KEY", "")
    client = LLMClient(primary_provider="openai", fallback_provider=None)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY não configurada"):
        client.generate("Teste")


def test_call_provider_direct_groq(monkeypatch):
    """Testa execução direta do método _call_groq."""
    monkeypatch.setenv("GROQ_API_KEY", "valid_key")
    client = LLMClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "Direto via Groq"}}]
    }
    with patch("httpx.Client.post", return_value=mock_resp):
        res = client._call_groq("Olá", timeout=5.0)
        assert res == "Direto via Groq"


def test_call_provider_direct_openai(monkeypatch):
    """Testa execução direta do método _call_openai."""
    monkeypatch.setenv("OPENAI_API_KEY", "valid_key")
    client = LLMClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "Direto via OpenAI"}}]
    }
    with patch("httpx.Client.post", return_value=mock_resp):
        res = client._call_openai("Olá", timeout=5.0)
        assert res == "Direto via OpenAI"
