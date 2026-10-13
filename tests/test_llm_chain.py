"""Cadeia ordenada de provedores (Ollama -> Groq -> DeepSeek) com disjuntor e teto diário.

Sem rede: `httpx.Client.post` e os métodos de chat são simulados.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.core import provider_guard
from src.core.llm_client import LLMClient

MESSAGES = [{"role": "user", "content": "oi"}]


class FakeClock:
    def __init__(self, now=1_700_000_000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    fake = FakeClock()
    provider_guard.configure(clock=fake, env={})
    return fake


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("LLM_PROVIDERS", "LLM_PROVIDER", "FALLBACK_PROVIDER", "DEEPSEEK_DAILY_CAP", "OLLAMA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")


def cloud_response(content="ok", model="m"):
    resp = MagicMock()
    resp.json.return_value = {
        "model": model,
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    }
    return resp


def router(handlers):
    """post falso: o comportamento depende do host. handlers: {'localhost': exc|resp, 'groq': ..., 'deepseek': ...}."""
    calls = []

    def fake_post(url, *args, **kwargs):
        calls.append(url)
        for key, behaviour in handlers.items():
            if key in url:
                if isinstance(behaviour, Exception):
                    raise behaviour
                return behaviour
        raise AssertionError(f"URL inesperada: {url}")

    fake_post.calls = calls
    return fake_post


def hosts(fake_post):
    return [("ollama" if "localhost" in u else "groq" if "groq" in u else "deepseek") for u in fake_post.calls]


DOWN = httpx.ConnectError("fora do ar")


# ------------------------------------ montagem da cadeia ------------------------------------ #

def test_chain_comes_from_llm_providers_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "ollama, groq ,deepseek")
    client = LLMClient()
    assert client.providers == ["ollama", "groq", "deepseek"]
    assert (client.primary_provider, client.fallback_provider) == ("ollama", "groq")


def test_explicit_arguments_keep_the_two_provider_chain(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "ollama,groq,deepseek")
    client = LLMClient(primary_provider="ollama", fallback_provider="groq")
    assert client.providers == ["ollama", "groq"]


def test_without_chain_env_the_legacy_variables_still_apply(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("FALLBACK_PROVIDER", "openai")
    assert LLMClient().providers == ["groq", "openai"]


def test_duplicates_are_dropped_keeping_the_first_position():
    assert LLMClient(providers=["ollama", "groq", "ollama", "deepseek"]).providers == ["ollama", "groq", "deepseek"]


def test_deepseek_is_a_supported_provider():
    assert "deepseek" in LLMClient.SUPPORTED_PROVIDERS


# ------------------------------------ ordem e passagem ao próximo ------------------------------------ #

def test_first_provider_answers_and_the_others_are_never_called(clock):
    post = router({"localhost": cloud_response("local")})
    with patch("httpx.Client.post", side_effect=post):
        result = LLMClient(providers=["ollama", "groq", "deepseek"]).chat(MESSAGES)
    assert hosts(post) == ["ollama"] and result.used_fallback is False


def test_groq_answers_when_ollama_is_down_and_deepseek_is_untouched(clock):
    post = router({"localhost": DOWN, "groq": cloud_response("da groq", "llama"), "deepseek": cloud_response()})
    with patch("httpx.Client.post", side_effect=post):
        result = LLMClient(providers=["ollama", "groq", "deepseek"]).chat(MESSAGES)
    assert hosts(post) == ["ollama", "groq"]
    assert result.provider == "groq" and result.used_fallback is True


def test_deepseek_is_the_last_resort_when_ollama_and_groq_fail(clock):
    post = router({"localhost": DOWN, "groq": httpx.ReadTimeout("lenta"), "deepseek": cloud_response("do deepseek", "deepseek-flash")})
    with patch("httpx.Client.post", side_effect=post):
        result = LLMClient(providers=["ollama", "groq", "deepseek"]).chat(MESSAGES)
    assert hosts(post) == ["ollama", "groq", "deepseek"]
    assert (result.provider, result.content, result.used_fallback) == ("deepseek", "do deepseek", True)


def test_generate_also_walks_the_whole_chain(clock):
    post = router({"localhost": DOWN, "groq": DOWN, "deepseek": cloud_response("texto final")})
    with patch("httpx.Client.post", side_effect=post):
        assert LLMClient(providers=["ollama", "groq", "deepseek"]).generate("pergunta") == "texto final"


def test_total_failure_names_every_provider_that_failed(clock):
    post = router({"localhost": DOWN, "groq": httpx.ReadTimeout("lenta"), "deepseek": httpx.ConnectError("sem rede")})
    with patch("httpx.Client.post", side_effect=post):
        with pytest.raises(RuntimeError, match="Falha total nos serviços de LLM") as exc:
            LLMClient(providers=["ollama", "groq", "deepseek"]).chat(MESSAGES)
    message = str(exc.value)
    for name in ("ollama", "groq", "deepseek"):
        assert f"'{name}'" in message


def test_missing_key_moves_on_to_the_next_provider(clock, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    post = router({"localhost": DOWN, "deepseek": cloud_response("ok")})
    with patch("httpx.Client.post", side_effect=post):
        result = LLMClient(providers=["ollama", "groq", "deepseek"]).chat(MESSAGES)
    assert result.provider == "deepseek"


def test_each_provider_gets_its_own_credentials(clock, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-secret")
    seen = {}

    def fake_post(url, *args, **kwargs):
        seen[url] = kwargs.get("headers", {}).get("Authorization")
        if "localhost" in url or "groq" in url:
            raise DOWN
        return cloud_response()

    with patch("httpx.Client.post", side_effect=fake_post):
        LLMClient(providers=["ollama", "groq", "deepseek"]).chat(MESSAGES)
    assert seen["http://localhost:11434/api/chat"] == "Bearer ollama-secret"
    assert seen["https://api.groq.com/openai/v1/chat/completions"] == "Bearer groq-key"
    assert seen["https://api.deepseek.com/chat/completions"] == "Bearer deepseek-key"


# ------------------------------------ DeepSeek ------------------------------------ #

def test_deepseek_request_uses_the_openai_compatible_endpoint_and_default_model(clock):
    captured = {}

    def fake_post(url, *args, **kwargs):
        captured.update(url=url, body=kwargs["json"])
        return cloud_response("ok", "deepseek-flash")

    tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    with patch("httpx.Client.post", side_effect=fake_post):
        LLMClient(providers=["deepseek"]).chat(MESSAGES, tools=tools, json_mode=True)
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["body"]["model"] == "deepseek-flash"
    assert captured["body"]["tools"] == tools and captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["temperature"] == 0.0


def test_deepseek_model_is_configurable(clock, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    captured = {}

    def fake_post(url, *args, **kwargs):
        captured["model"] = kwargs["json"]["model"]
        return cloud_response()

    with patch("httpx.Client.post", side_effect=fake_post):
        LLMClient(providers=["deepseek"]).chat(MESSAGES)
    assert captured["model"] == "deepseek-v4-pro"


def test_deepseek_without_key_fails_with_a_clear_message(clock, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY não configurada"):
        LLMClient(providers=["deepseek"]).chat(MESSAGES)


def test_deepseek_tool_calls_are_normalised_like_the_other_providers(clock):
    resp = MagicMock()
    resp.json.return_value = {
        "model": "deepseek-flash",
        "choices": [{"message": {"content": None, "tool_calls": [{"function": {"name": "resolve_politician", "arguments": '{"nome_busca": "Lula"}'}}]}}],
        "usage": {},
    }
    with patch("httpx.Client.post", return_value=resp):
        result = LLMClient(providers=["deepseek"]).chat(MESSAGES)
    assert result.tool_calls == [{"name": "resolve_politician", "arguments": {"nome_busca": "Lula"}}]


# ------------------------------------ disjuntor na cadeia ------------------------------------ #

def test_after_three_failures_ollama_is_skipped_without_waiting_for_its_timeout(clock):
    post = router({"localhost": DOWN, "groq": cloud_response()})
    client = LLMClient(providers=["ollama", "groq"])
    with patch("httpx.Client.post", side_effect=post):
        for _ in range(3):
            client.chat(MESSAGES)
        post.calls.clear()
        client.chat(MESSAGES)
    assert hosts(post) == ["groq"], "o Ollama não deve ser tentado com o disjuntor aberto"


def test_ollama_comes_back_after_the_cooldown_when_it_recovers(clock):
    handlers = {"localhost": DOWN, "groq": cloud_response("nuvem")}
    post = router(handlers)
    client = LLMClient(providers=["ollama", "groq"])
    with patch("httpx.Client.post", side_effect=post):
        for _ in range(3):
            client.chat(MESSAGES)
        handlers["localhost"] = MagicMock(json=MagicMock(return_value={"message": {"content": "local"}, "model": "qwen2.5:7b"}))
        clock.advance(121)
        first = client.chat(MESSAGES)
        second = client.chat(MESSAGES)
    assert first.provider == "ollama" and second.provider == "ollama"


def test_a_failed_trial_keeps_ollama_out_for_another_cooldown(clock):
    post = router({"localhost": DOWN, "groq": cloud_response()})
    client = LLMClient(providers=["ollama", "groq"])
    with patch("httpx.Client.post", side_effect=post):
        for _ in range(3):
            client.chat(MESSAGES)
        clock.advance(121)
        client.chat(MESSAGES)  # tentativa de teste: falha de novo
        post.calls.clear()
        client.chat(MESSAGES)
    assert hosts(post) == ["groq"]


def test_missing_key_is_a_configuration_error_and_does_not_open_the_breaker(clock, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    client = LLMClient(providers=["groq"])
    for _ in range(5):
        with pytest.raises(RuntimeError, match="GROQ_API_KEY não configurada"):
            client.chat(MESSAGES)
    assert provider_guard.guards.breaker("groq").state == "closed"


def test_when_every_breaker_is_open_the_chain_still_tries_instead_of_failing_blind(clock):
    for provider in ("ollama", "groq"):
        for _ in range(3):
            provider_guard.guards.breaker(provider).record_failure()
    post = router({"localhost": DOWN, "groq": cloud_response("voltou")})
    with patch("httpx.Client.post", side_effect=post):
        result = LLMClient(providers=["ollama", "groq"]).chat(MESSAGES)
    assert result.provider == "groq"
    assert hosts(post) == ["ollama", "groq"]


def test_breaker_state_is_shared_between_client_instances(clock):
    """Roteador e juiz criam clientes próprios dentro do mesmo processo de serviço: o estado é por provedor."""
    post = router({"localhost": DOWN, "groq": cloud_response()})
    with patch("httpx.Client.post", side_effect=post):
        for _ in range(3):
            LLMClient(providers=["ollama", "groq"]).chat(MESSAGES)
        post.calls.clear()
        LLMClient(providers=["ollama", "groq"]).chat(MESSAGES)
    assert hosts(post) == ["groq"]


# ------------------------------------ teto diário na cadeia ------------------------------------ #

def test_deepseek_stops_at_the_daily_cap_and_the_chain_reports_it(clock):
    provider_guard.configure(clock=clock, env={"DEEPSEEK_DAILY_CAP": "2"})
    post = router({"localhost": DOWN, "groq": DOWN, "deepseek": cloud_response("ok")})
    client = LLMClient(providers=["ollama", "groq", "deepseek"])
    with patch("httpx.Client.post", side_effect=post):
        assert client.chat(MESSAGES).provider == "deepseek"
        assert client.chat(MESSAGES).provider == "deepseek"
        post.calls.clear()
        with pytest.raises(RuntimeError, match="limite diário"):
            client.chat(MESSAGES)
    assert "deepseek" not in hosts(post), "acima do teto, nenhuma chamada paga é feita"


def test_the_cap_resets_the_next_day(clock):
    provider_guard.configure(clock=clock, env={"DEEPSEEK_DAILY_CAP": "1", "LLM_BREAKER_FAILURES": "100"})
    post = router({"localhost": DOWN, "groq": DOWN, "deepseek": cloud_response("ok")})
    client = LLMClient(providers=["ollama", "groq", "deepseek"])
    with patch("httpx.Client.post", side_effect=post):
        client.chat(MESSAGES)
        with pytest.raises(RuntimeError, match="limite diário"):
            client.chat(MESSAGES)
        clock.advance(24 * 3600)
        assert client.chat(MESSAGES).provider == "deepseek"


def test_failed_deepseek_attempts_count_towards_the_cap(clock):
    provider_guard.configure(clock=clock, env={"DEEPSEEK_DAILY_CAP": "1", "LLM_BREAKER_FAILURES": "100"})
    post = router({"localhost": DOWN, "groq": DOWN, "deepseek": httpx.ReadTimeout("lenta")})
    client = LLMClient(providers=["ollama", "groq", "deepseek"])
    with patch("httpx.Client.post", side_effect=post):
        with pytest.raises(RuntimeError):
            client.chat(MESSAGES)
        post.calls.clear()
        with pytest.raises(RuntimeError, match="limite diário"):
            client.chat(MESSAGES)
    assert "deepseek" not in hosts(post)


def test_free_providers_have_no_daily_cap_by_default(clock):
    post = router({"localhost": cloud_response("local")})
    client = LLMClient(providers=["ollama", "groq", "deepseek"])
    with patch("httpx.Client.post", side_effect=post):
        for _ in range(300):
            assert client.chat(MESSAGES).provider == "ollama"


def test_cap_does_not_consume_budget_when_an_earlier_provider_answers(clock):
    provider_guard.configure(clock=clock, env={"DEEPSEEK_DAILY_CAP": "1"})
    post = router({"localhost": cloud_response("local")})
    client = LLMClient(providers=["ollama", "groq", "deepseek"])
    with patch("httpx.Client.post", side_effect=post):
        for _ in range(5):
            client.chat(MESSAGES)
    assert provider_guard.guards.cap("deepseek").used == 0
