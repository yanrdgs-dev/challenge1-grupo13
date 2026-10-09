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


# --------------------------------------------------------------------------- #
# LLMClient.chat: mensagens + tools, tool calls normalizadas e uso de tokens
# --------------------------------------------------------------------------- #

MESSAGES = [
    {"role": "system", "content": "Você é um roteador."},
    {"role": "user", "content": "Claim de teste"},
]
TOOLS = [{"type": "function", "function": {"name": "resolve_politician", "parameters": {}}}]


def _ollama_chat_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "model": "qwen2.5:7b",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "resolve_politician", "arguments": {"nome_busca": "Fulano"}}}
            ],
        },
        "prompt_eval_count": 120,
        "eval_count": 30,
    }
    return resp


def test_chat_ollama_success_returns_tool_calls_and_usage():
    client = LLMClient(primary_provider="ollama", fallback_provider="")

    with patch("httpx.Client.post", return_value=_ollama_chat_response()) as mock_post:
        result = client.chat(MESSAGES, tools=TOOLS, model="qwen2.5:7b")

    assert "/api/chat" in mock_post.call_args[0][0]
    body = mock_post.call_args[1]["json"]
    assert body["model"] == "qwen2.5:7b"
    assert body["tools"] == TOOLS
    assert body["stream"] is False
    assert result.provider == "ollama"
    assert result.model == "qwen2.5:7b"
    assert result.tool_calls == [
        {"name": "resolve_politician", "arguments": {"nome_busca": "Fulano"}}
    ]
    assert result.usage == {"input_tokens": 120, "output_tokens": 30}
    assert result.latency_ms >= 0


def test_chat_without_tool_calls_returns_content():
    client = LLMClient(primary_provider="ollama", fallback_provider="")
    resp = MagicMock()
    resp.json.return_value = {
        "message": {"role": "assistant", "content": '{"veredito": "FALSO"}'},
        "prompt_eval_count": 10,
        "eval_count": 5,
    }

    with patch("httpx.Client.post", return_value=resp) as mock_post:
        result = client.chat(MESSAGES, json_mode=True)

    assert mock_post.call_args[1]["json"]["format"] == "json"
    assert "tools" not in mock_post.call_args[1]["json"]
    assert result.content == '{"veredito": "FALSO"}'
    assert result.tool_calls == []


def test_chat_timeout_without_fallback_raises_runtime_error():
    client = LLMClient(primary_provider="ollama", fallback_provider="")

    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("timeout")):
        with pytest.raises(RuntimeError, match="nenhum fallback"):
            client.chat(MESSAGES, tools=TOOLS)


def test_chat_falls_back_to_groq_and_parses_tool_arguments(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_mock_key")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.1-8b-instant")
    client = LLMClient(primary_provider="ollama", fallback_provider="groq")

    groq_resp = MagicMock()
    groq_resp.json.return_value = {
        "model": "llama-3.1-8b-instant",
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "function": {
                                "name": "resolve_proposition",
                                "arguments": '{"sigla_tipo": "PL", "numero": 1, "ano": 2023}',
                            }
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 200, "completion_tokens": 40},
    }

    def fake_post(url, *args, **kwargs):
        if "localhost" in url:
            raise httpx.TimeoutException("ollama fora do ar")
        return groq_resp

    with patch("httpx.Client.post", side_effect=fake_post):
        result = client.chat(MESSAGES, tools=TOOLS, model="qwen2.5:7b")

    assert result.provider == "groq"
    assert result.model == "llama-3.1-8b-instant"
    assert result.used_fallback is True
    assert result.tool_calls == [
        {"name": "resolve_proposition", "arguments": {"sigla_tipo": "PL", "numero": 1, "ano": 2023}}
    ]
    assert result.usage == {"input_tokens": 200, "output_tokens": 40}


def test_chat_both_providers_fail_raises_runtime_error(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_mock_key")
    client = LLMClient(primary_provider="ollama", fallback_provider="groq")

    with patch("httpx.Client.post", side_effect=httpx.ConnectError("sem rede")):
        with pytest.raises(RuntimeError, match="Falha total"):
            client.chat(MESSAGES)


def test_chat_rejects_empty_messages():
    client = LLMClient()
    with pytest.raises(ValueError, match="messages"):
        client.chat([])


# --------------------------------------------------------------------------- #
# Instrumentação: cada tentativa de chat vira uma generation no Langfuse
# --------------------------------------------------------------------------- #

from contextlib import contextmanager


class _FakeObs:
    def __init__(self, name, as_type, kwargs):
        self.name, self.as_type, self.kwargs = name, as_type, kwargs
        self.updates = []

    def update(self, **kw):
        self.updates.append(kw)

    @property
    def last(self):
        merged = {}
        for u in self.updates:
            merged.update(u)
        return merged


@pytest.fixture
def observations():
    """Substitui tracing.observation e registra as generations abertas."""
    recorded = []

    @contextmanager
    def fake(name, as_type="span", **kwargs):
        obs = _FakeObs(name, as_type, kwargs)
        recorded.append(obs)
        yield obs

    with patch("src.core.llm_client.tracing.observation", fake):
        yield recorded


def test_chat_records_generation_with_model_tokens_and_provider(observations):
    client = LLMClient(primary_provider="ollama", fallback_provider="")

    with patch("httpx.Client.post", return_value=_ollama_chat_response()):
        client.chat(MESSAGES, tools=TOOLS, model="qwen2.5:7b")

    assert len(observations) == 1
    gen = observations[0]
    assert (gen.name, gen.as_type) == ("llm.chat", "generation")
    assert gen.kwargs["model"] == "qwen2.5:7b"
    assert gen.kwargs["input"] == MESSAGES
    assert gen.kwargs["metadata"]["provider"] == "ollama"
    assert gen.kwargs["metadata"]["fallback"] is False
    assert gen.last["usage_details"] == {"input": 120, "output": 30}
    assert gen.last["output"] == [
        {"name": "resolve_politician", "arguments": {"nome_busca": "Fulano"}}
    ]
    assert gen.last["metadata"]["latency_ms"] >= 0


def test_chat_records_text_output_when_no_tool_calls(observations):
    client = LLMClient(primary_provider="ollama", fallback_provider="")
    resp = MagicMock()
    resp.json.return_value = {
        "message": {"role": "assistant", "content": "texto"},
        "prompt_eval_count": 3,
        "eval_count": 4,
    }
    with patch("httpx.Client.post", return_value=resp):
        client.chat(MESSAGES)
    assert observations[0].last["output"] == "texto"


def test_chat_omits_usage_when_provider_does_not_report(observations):
    client = LLMClient(primary_provider="ollama", fallback_provider="")
    resp = MagicMock()
    resp.json.return_value = {"message": {"role": "assistant", "content": "x"}}
    with patch("httpx.Client.post", return_value=resp):
        client.chat(MESSAGES)
    assert "usage_details" not in observations[0].last


def test_chat_fallback_records_failed_and_successful_generations(observations, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_mock_key")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.1-8b-instant")
    client = LLMClient(primary_provider="ollama", fallback_provider="groq")

    groq_resp = MagicMock()
    groq_resp.json.return_value = {
        "model": "llama-3.1-8b-instant",
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 2},
    }

    def fake_post(url, *args, **kwargs):
        if "localhost" in url:
            raise httpx.TimeoutException("ollama fora do ar")
        return groq_resp

    with patch("httpx.Client.post", side_effect=fake_post):
        client.chat(MESSAGES, model="qwen2.5:7b")

    assert len(observations) == 2
    failed, ok = observations
    assert failed.kwargs["metadata"]["provider"] == "ollama"
    assert failed.last["level"] == "ERROR"
    assert "ollama fora do ar" in failed.last["status_message"]
    assert ok.kwargs["metadata"]["provider"] == "groq"
    assert ok.kwargs["metadata"]["fallback"] is True
    assert ok.kwargs["model"] == "llama-3.1-8b-instant"
    assert ok.last["usage_details"] == {"input": 7, "output": 2}


def test_chat_result_is_unchanged_when_tracing_is_disabled():
    """Com o tracing desligado (padrão nos testes), o resultado é o mesmo."""
    client = LLMClient(primary_provider="ollama", fallback_provider="")
    with patch("httpx.Client.post", return_value=_ollama_chat_response()):
        result = client.chat(MESSAGES, tools=TOOLS)
    assert result.tool_calls[0]["name"] == "resolve_politician"


# --------------------------------------------------------------------------- #
# Determinismo: temperatura 0 por padrão (baseline comparável entre execuções)
# --------------------------------------------------------------------------- #

def test_ollama_chat_uses_temperature_zero_by_default(monkeypatch):
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    client = LLMClient(primary_provider="ollama", fallback_provider="")
    with patch("httpx.Client.post", return_value=_ollama_chat_response()) as mock_post:
        client.chat(MESSAGES)
    assert mock_post.call_args[1]["json"]["options"] == {"temperature": 0.0}


def test_temperature_is_configurable_by_env(monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "0.7")
    client = LLMClient(primary_provider="ollama", fallback_provider="")
    with patch("httpx.Client.post", return_value=_ollama_chat_response()) as mock_post:
        client.chat(MESSAGES)
    assert mock_post.call_args[1]["json"]["options"] == {"temperature": 0.7}


def test_invalid_temperature_env_falls_back_to_zero(monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "abc")
    client = LLMClient(primary_provider="ollama", fallback_provider="")
    with patch("httpx.Client.post", return_value=_ollama_chat_response()) as mock_post:
        client.chat(MESSAGES)
    assert mock_post.call_args[1]["json"]["options"] == {"temperature": 0.0}


def test_groq_chat_also_uses_temperature(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_mock_key")
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    client = LLMClient(primary_provider="groq", fallback_provider="")
    resp = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    with patch("httpx.Client.post", return_value=resp) as mock_post:
        client.chat(MESSAGES)
    assert mock_post.call_args[1]["json"]["temperature"] == 0.0


def test_generation_metadata_records_the_temperature(observations, monkeypatch):
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    client = LLMClient(primary_provider="ollama", fallback_provider="")
    with patch("httpx.Client.post", return_value=_ollama_chat_response()):
        client.chat(MESSAGES)
    assert observations[0].kwargs["model_parameters"] == {"temperature": 0.0}


# --------------------------------------------------------------------------- #
# Versão do prompt: a generation é ligada ao prompt do Langfuse (tarefa 4.3)
# --------------------------------------------------------------------------- #


def test_chat_links_generation_to_prompt_client(observations):
    client = LLMClient(primary_provider="ollama", fallback_provider="")
    prompt_client = MagicMock(name="prompt_client")

    with patch("httpx.Client.post", return_value=_ollama_chat_response()):
        client.chat(MESSAGES, prompt=prompt_client)

    assert observations[0].kwargs["prompt"] is prompt_client


def test_chat_without_prompt_does_not_pass_prompt_to_generation(observations):
    client = LLMClient(primary_provider="ollama", fallback_provider="")

    with patch("httpx.Client.post", return_value=_ollama_chat_response()):
        client.chat(MESSAGES)

    assert "prompt" not in observations[0].kwargs


# --------------------------------------------------------------------------- #
# D.1: Ollama atrás de túnel com proxy que exige Authorization: Bearer
# --------------------------------------------------------------------------- #

SECRET = "chave-super-secreta-do-tunel"


def _generate_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"response": "ok"}
    return resp


def test_chat_sends_bearer_header_when_ollama_api_key_is_set(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", SECRET)
    client = LLMClient(primary_provider="ollama", fallback_provider="")
    with patch("httpx.Client.post", return_value=_ollama_chat_response()) as mock_post:
        client.chat(MESSAGES)
    assert mock_post.call_args[1]["headers"] == {"Authorization": f"Bearer {SECRET}"}


def test_generate_sends_bearer_header_when_ollama_api_key_is_set(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", SECRET)
    client = LLMClient(primary_provider="ollama", fallback_provider="")
    with patch("httpx.Client.post", return_value=_generate_response()) as mock_post:
        client.generate("Olá")
    assert mock_post.call_args[1]["headers"] == {"Authorization": f"Bearer {SECRET}"}


@pytest.mark.parametrize("value", [None, "", "   "])
def test_no_authorization_header_without_a_usable_key(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OLLAMA_API_KEY", value)
    client = LLMClient(primary_provider="ollama", fallback_provider="")
    with patch("httpx.Client.post", return_value=_ollama_chat_response()) as mock_post:
        client.chat(MESSAGES)
    assert not mock_post.call_args[1].get("headers")


def test_ollama_key_is_not_sent_to_the_fallback_provider(monkeypatch):
    """A chave do túnel é só do Ollama: o Groq recebe a própria chave, nunca a do proxy."""
    monkeypatch.setenv("OLLAMA_API_KEY", SECRET)
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    client = LLMClient(primary_provider="ollama", fallback_provider="groq")
    groq_resp = MagicMock()
    groq_resp.json.return_value = {
        "model": "llama",
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    with patch("httpx.Client.post", side_effect=[httpx.ConnectError("caiu"), groq_resp]) as mock_post:
        client.chat(MESSAGES)
    groq_call = mock_post.call_args_list[1]
    assert SECRET not in str(groq_call)


def test_failure_message_does_not_leak_the_ollama_key(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", SECRET)
    client = LLMClient(primary_provider="ollama", fallback_provider="")
    with patch("httpx.Client.post", side_effect=httpx.ConnectError("conexão recusada")):
        with pytest.raises(RuntimeError) as exc_info:
            client.chat(MESSAGES)
    assert SECRET not in str(exc_info.value)
