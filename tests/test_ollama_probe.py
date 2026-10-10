"""Teste rápido de vida do Ollama (GET /api/tags com timeout curto) antes de cada tentativa.

O Ollama chega à VM por um túnel SSH reverso: com o Mac fora, o túnel aceita a conexão e não responde, e a
falha só aparecia no timeout cheio (30 s no roteador, 60 s no juiz). O teste descobre em segundos.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.core import provider_guard
from src.core.llm_client import LLMClient

MESSAGES = [{"role": "user", "content": "oi"}]
OLLAMA_CHAT = {"message": {"content": "local"}, "model": "qwen2.5:7b"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("LLM_PROVIDERS", "LLM_PROVIDER", "FALLBACK_PROVIDER", "OLLAMA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OLLAMA_PROBE_TIMEOUT", "3")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")


def ok_response(payload=None):
    resp = MagicMock()
    resp.json.return_value = payload or {}
    return resp


def post_router(ollama=None):
    """post falso: o Ollama responde `ollama` (resposta ou exceção); a Groq responde sempre."""
    calls = []

    def fake_post(url, *args, **kwargs):
        calls.append(url)
        if "localhost" in url:
            if isinstance(ollama, Exception):
                raise ollama
            return ok_response(ollama or OLLAMA_CHAT)
        return ok_response({"choices": [{"message": {"content": "da groq"}}], "usage": {}})

    fake_post.calls = calls
    return fake_post


def chat_calls(fake_post):
    return [u for u in fake_post.calls if "localhost" in u]


def test_probe_ok_lets_the_chat_proceed():
    post = post_router()
    with patch("httpx.Client.get", return_value=ok_response()) as get, patch("httpx.Client.post", side_effect=post):
        result = LLMClient(providers=["ollama", "groq"]).chat(MESSAGES, model="qwen2.5:7b")
    assert result.provider == "ollama"
    assert get.call_args[0][0] == "http://localhost:11434/api/tags"
    assert chat_calls(post), "com o Ollama vivo, o chat segue"


def test_probe_uses_the_short_timeout_not_the_chat_timeout():
    seen = {}

    def fake_get(self, url, **kwargs):
        seen["timeout"] = self.timeout.read
        return ok_response()

    with patch("httpx.Client.get", autospec=True, side_effect=fake_get), \
         patch("httpx.Client.post", side_effect=post_router()):
        LLMClient(providers=["ollama"], timeout=60.0).chat(MESSAGES)
    assert seen["timeout"] == 3.0


@pytest.mark.parametrize(
    "failure",
    [httpx.ReadTimeout("tunel mudo"), httpx.ConnectError("recusou"), httpx.ConnectTimeout("sem rota")],
)
def test_dead_probe_skips_ollama_without_waiting_and_falls_to_the_next_provider(failure):
    post = post_router()
    with patch("httpx.Client.get", side_effect=failure), patch("httpx.Client.post", side_effect=post):
        result = LLMClient(providers=["ollama", "groq"]).chat(MESSAGES)
    assert result.provider == "groq" and result.used_fallback is True
    assert chat_calls(post) == [], "o chat do Ollama nem é tentado quando o teste falha"


def test_probe_http_error_counts_as_down():
    bad = MagicMock()
    bad.raise_for_status.side_effect = httpx.HTTPStatusError("502", request=MagicMock(), response=MagicMock())
    post = post_router()
    with patch("httpx.Client.get", return_value=bad), patch("httpx.Client.post", side_effect=post):
        result = LLMClient(providers=["ollama", "groq"]).chat(MESSAGES)
    assert result.provider == "groq" and chat_calls(post) == []


def test_failed_probes_open_the_breaker_and_then_the_probe_stops_being_called():
    post = post_router()
    client = LLMClient(providers=["ollama", "groq"])
    with patch("httpx.Client.get", side_effect=httpx.ReadTimeout("mudo")) as get, \
         patch("httpx.Client.post", side_effect=post):
        for _ in range(3):
            client.chat(MESSAGES)
        assert get.call_count == 3
        client.chat(MESSAGES)
    assert get.call_count == 3, "com o disjuntor aberto o Ollama nem é testado"
    assert provider_guard.guards.breaker("ollama").state == "open"


def test_probe_is_also_used_by_generate():
    post = post_router()
    with patch("httpx.Client.get", side_effect=httpx.ReadTimeout("mudo")), patch("httpx.Client.post", side_effect=post):
        assert LLMClient(providers=["ollama", "groq"]).generate("pergunta") == "da groq"
    assert chat_calls(post) == []


def test_zero_disables_the_probe(monkeypatch):
    monkeypatch.setenv("OLLAMA_PROBE_TIMEOUT", "0")
    with patch("httpx.Client.get") as get, patch("httpx.Client.post", side_effect=post_router()):
        LLMClient(providers=["ollama"]).chat(MESSAGES)
    get.assert_not_called()


@pytest.mark.parametrize("bad", ["", "abc", "-2"])
def test_invalid_value_falls_back_to_three_seconds(monkeypatch, bad):
    monkeypatch.setenv("OLLAMA_PROBE_TIMEOUT", bad)
    seen = {}

    def fake_get(self, url, **kwargs):
        seen["timeout"] = self.timeout.read
        return ok_response()

    with patch("httpx.Client.get", autospec=True, side_effect=fake_get), \
         patch("httpx.Client.post", side_effect=post_router()):
        LLMClient(providers=["ollama"]).chat(MESSAGES)
    assert seen["timeout"] == 3.0


def test_probe_sends_the_tunnel_bearer_key(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "segredo-do-tunel")
    with patch("httpx.Client.get", return_value=ok_response()) as get, patch("httpx.Client.post", side_effect=post_router()):
        LLMClient(providers=["ollama"]).chat(MESSAGES)
    assert get.call_args[1]["headers"] == {"Authorization": "Bearer segredo-do-tunel"}


def test_probe_sends_no_authorization_header_without_a_key():
    with patch("httpx.Client.get", return_value=ok_response()) as get, patch("httpx.Client.post", side_effect=post_router()):
        LLMClient(providers=["ollama"]).chat(MESSAGES)
    assert not get.call_args[1].get("headers")


def test_cloud_providers_are_never_probed():
    with patch("httpx.Client.get") as get, patch("httpx.Client.post", side_effect=post_router()):
        LLMClient(providers=["groq"]).chat(MESSAGES)
    get.assert_not_called()


def test_probe_failure_message_does_not_leak_the_key(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "segredo-do-tunel")
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("recusou")):
        with pytest.raises(RuntimeError) as exc:
            LLMClient(providers=["ollama"]).chat(MESSAGES)
    assert "segredo-do-tunel" not in str(exc.value)
