"""Estratégia round-robin: cada requisição começa num provedor diferente (Ollama, Groq, DeepSeek, Ollama, ...).

Se o provedor da vez falha (fora do ar, limite acabou, chave ausente, disjuntor aberto, teto diário), a requisição
passa ao próximo da rotação: Groq fora manda para o DeepSeek, DeepSeek fora manda para o Ollama. Sem rede.
"""

from unittest.mock import patch

import httpx
import pytest

from src.core import provider_guard
from src.core.llm_client import LLMClient
from tests.test_llm_chain import DOWN, MESSAGES, cloud_response, hosts, router

CHAIN = ["ollama", "groq", "deepseek"]
RATE_LIMIT = httpx.HTTPStatusError("429 Too Many Requests", request=httpx.Request("POST", "http://x"),
                                   response=httpx.Response(429))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("LLM_PROVIDERS", "LLM_PROVIDER", "FALLBACK_PROVIDER", "LLM_STRATEGY", "DEEPSEEK_DAILY_CAP",
                 "OLLAMA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    provider_guard.configure(env={})
    yield
    provider_guard.reset()


def healthy():
    return {"localhost": cloud_response("local"), "groq": cloud_response("groq"), "deepseek": cloud_response("deepseek")}


def run(client, n, handlers=None):
    post = router(handlers or healthy())
    with patch("httpx.Client.post", side_effect=post):
        results = [client.chat(MESSAGES) for _ in range(n)]
    return post, results


# ------------------------------------ configuração ------------------------------------ #

def test_default_strategy_is_the_ordered_fallback_chain():
    assert LLMClient(providers=CHAIN).strategy == "fallback"


def test_strategy_comes_from_the_env(monkeypatch):
    monkeypatch.setenv("LLM_STRATEGY", "round_robin")
    assert LLMClient(providers=CHAIN).strategy == "round_robin"


@pytest.mark.parametrize("raw, expected", [("Round-Robin", "round_robin"), ("round_robin", "round_robin"),
                                           ("roundrobin", "round_robin"), ("fallback", "fallback"),
                                           ("qualquer coisa", "fallback"), ("", "fallback")])
def test_strategy_is_normalized_and_unknown_values_fall_back_to_the_ordered_chain(raw, expected):
    assert LLMClient(providers=CHAIN, strategy=raw).strategy == expected


def test_explicit_strategy_beats_the_env(monkeypatch):
    monkeypatch.setenv("LLM_STRATEGY", "round_robin")
    assert LLMClient(providers=CHAIN, strategy="fallback").strategy == "fallback"


# ------------------------------------ a rotação ------------------------------------ #

def test_requests_rotate_ollama_then_groq_then_deepseek_then_ollama_again():
    post, results = run(LLMClient(providers=CHAIN, strategy="round_robin"), 7)
    assert hosts(post) == ["ollama", "groq", "deepseek", "ollama", "groq", "deepseek", "ollama"]
    assert [r.provider for r in results] == ["ollama", "groq", "deepseek", "ollama", "groq", "deepseek", "ollama"]


def test_a_provider_that_answers_in_its_turn_is_not_a_fallback():
    _, results = run(LLMClient(providers=CHAIN, strategy="round_robin"), 3)
    assert [r.used_fallback for r in results] == [False, False, False]


def test_fallback_strategy_still_always_starts_at_the_first_provider():
    post, _ = run(LLMClient(providers=CHAIN, strategy="fallback"), 3)
    assert hosts(post) == ["ollama", "ollama", "ollama"]


def test_generate_also_rotates():
    client = LLMClient(providers=CHAIN, strategy="round_robin")
    post = router(healthy())
    with patch("httpx.Client.post", side_effect=post):
        texts = [client.generate("pergunta") for _ in range(3)]
    assert hosts(post) == ["ollama", "groq", "deepseek"] and texts == ["local", "groq", "deepseek"]


def test_two_clients_rotate_independently():
    a, b = LLMClient(providers=CHAIN, strategy="round_robin"), LLMClient(providers=CHAIN, strategy="round_robin")
    post = router(healthy())
    with patch("httpx.Client.post", side_effect=post):
        a.chat(MESSAGES)
        a.chat(MESSAGES)
        b.chat(MESSAGES)
    assert hosts(post) == ["ollama", "groq", "ollama"]


def test_a_failed_request_still_advances_the_rotation_once():
    """O contador anda por requisição, não por tentativa: o failover não desloca a fila dos demais."""
    client = LLMClient(providers=CHAIN, strategy="round_robin")
    post = router({**healthy(), "groq": DOWN})
    with patch("httpx.Client.post", side_effect=post):
        client.chat(MESSAGES)      # vez do Ollama
        client.chat(MESSAGES)      # vez do Groq: falha e vai para o DeepSeek
        client.chat(MESSAGES)      # vez do DeepSeek (e não do Groq de novo)
    assert hosts(post) == ["ollama", "groq", "deepseek", "deepseek"]


# ------------------------------------ passagem ao próximo da rotação ------------------------------------ #

def test_groq_down_sends_its_turn_to_deepseek():
    client = LLMClient(providers=CHAIN, strategy="round_robin")
    post = router({**healthy(), "groq": DOWN})
    with patch("httpx.Client.post", side_effect=post):
        client.chat(MESSAGES)
        result = client.chat(MESSAGES)
    assert hosts(post) == ["ollama", "groq", "deepseek"]
    assert (result.provider, result.used_fallback) == ("deepseek", True)


def test_groq_rate_limit_exhausted_sends_its_turn_to_deepseek():
    client = LLMClient(providers=CHAIN, strategy="round_robin")
    post = router({**healthy(), "groq": RATE_LIMIT})
    with patch("httpx.Client.post", side_effect=post):
        client.chat(MESSAGES)
        result = client.chat(MESSAGES)
    assert result.provider == "deepseek"


def test_deepseek_down_wraps_around_to_ollama():
    client = LLMClient(providers=CHAIN, strategy="round_robin")
    post = router({**healthy(), "deepseek": DOWN})
    with patch("httpx.Client.post", side_effect=post):
        client.chat(MESSAGES)
        client.chat(MESSAGES)
        result = client.chat(MESSAGES)
    assert hosts(post) == ["ollama", "groq", "deepseek", "ollama"]
    assert (result.provider, result.used_fallback) == ("ollama", True)


def test_missing_groq_key_skips_to_deepseek_without_failing(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    client = LLMClient(providers=CHAIN, strategy="round_robin")
    post = router({"localhost": cloud_response("local"), "deepseek": cloud_response("deepseek")})
    with patch("httpx.Client.post", side_effect=post):
        client.chat(MESSAGES)
        result = client.chat(MESSAGES)
    assert result.provider == "deepseek"


def test_provider_with_an_open_breaker_is_skipped_in_its_turn():
    provider_guard.configure(env={"LLM_BREAKER_FAILURES": "1", "LLM_BREAKER_COOLDOWN": "600"})
    client = LLMClient(providers=CHAIN, strategy="round_robin")
    post = router({**healthy(), "groq": DOWN})
    with patch("httpx.Client.post", side_effect=post):
        for _ in range(4):
            client.chat(MESSAGES)           # ollama, groq(falha→deepseek), deepseek, ollama
        second_lap = client.chat(MESSAGES)  # vez do Groq com disjuntor aberto: nem tenta
    assert hosts(post).count("groq") == 1 and second_lap.provider == "deepseek"


def test_deepseek_daily_cap_sends_its_turn_to_the_next_provider():
    provider_guard.configure(env={"DEEPSEEK_DAILY_CAP": "1"})
    client = LLMClient(providers=CHAIN, strategy="round_robin")
    post, results = run(client, 6)
    # 1ª volta: ollama, groq, deepseek (usa o único crédito). 2ª volta: ollama, groq e deepseek esgotado → ollama
    assert [r.provider for r in results] == ["ollama", "groq", "deepseek", "ollama", "groq", "ollama"]


def test_total_failure_still_reports_every_provider():
    client = LLMClient(providers=CHAIN, strategy="round_robin")
    post = router({"localhost": DOWN, "groq": DOWN, "deepseek": DOWN})
    with patch("httpx.Client.post", side_effect=post):
        with pytest.raises(RuntimeError, match="Falha total nos serviços de LLM"):
            client.chat(MESSAGES)
    assert sorted(hosts(post)) == ["deepseek", "groq", "ollama"]


def test_cloud_providers_keep_the_longer_timeout_even_when_they_open_the_rotation():
    """O Ollama usa o timeout curto de LLM_TIMEOUT; Groq e DeepSeek usam o de nuvem, mesmo quando a vez é deles."""
    client = LLMClient(providers=CHAIN, strategy="round_robin", timeout=3.0)
    seen = {}

    def fake_post(url, *args, **kwargs):
        seen["groq" if "groq" in url else "deepseek" if "deepseek" in url else "ollama"] = kwargs.get("timeout")
        return cloud_response("ok")

    with patch("httpx.Client.post", side_effect=fake_post):
        for _ in range(3):
            client.chat(MESSAGES)
    assert seen["ollama"] == 3.0
    assert seen["groq"] == seen["deepseek"] == client.fallback_timeout
