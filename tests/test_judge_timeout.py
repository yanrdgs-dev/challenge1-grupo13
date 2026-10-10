"""Timeout do roteador ao chamar o juiz.

Incidente: o juiz esperou 60 s o Ollama (fora do ar) e só depois foi para a Groq, mas o roteador desistia
exatamente aos 60 s. A resposta da Groq chegou e foi descartada. O roteador precisa esperar mais do que a
pior cadeia do juiz: timeout do primeiro provedor + um timeout de contingência por provedor seguinte + folga.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.services import router_service

ENV_VARS = ("JUDGE_SERVICE_TIMEOUT", "JUDGE_LLM_TIMEOUT", "FALLBACK_TIMEOUT")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def three_providers():
    with patch.object(router_service.llm_client, "providers", ["ollama", "groq", "deepseek"]), \
         patch.object(router_service.llm_client, "fallback_timeout", 10.0):
        yield


def test_default_covers_the_judge_worst_case_with_margin(three_providers):
    # 60 s no Ollama + 10 s na Groq + 10 s no DeepSeek + 15 s de folga
    assert router_service.judge_call_timeout() == 95.0


def test_it_follows_the_judge_llm_timeout(three_providers, monkeypatch):
    monkeypatch.setenv("JUDGE_LLM_TIMEOUT", "120")
    assert router_service.judge_call_timeout() == 155.0


def test_it_follows_the_fallback_timeout_of_the_client(three_providers):
    router_service.llm_client.fallback_timeout = 30.0
    assert router_service.judge_call_timeout() == 60.0 + 2 * 30.0 + 15.0


def test_it_follows_the_length_of_the_chain():
    with patch.object(router_service.llm_client, "providers", ["groq"]), \
         patch.object(router_service.llm_client, "fallback_timeout", 10.0):
        assert router_service.judge_call_timeout() == 60.0 + 15.0


def test_explicit_setting_wins(three_providers, monkeypatch):
    monkeypatch.setenv("JUDGE_SERVICE_TIMEOUT", "200")
    assert router_service.judge_call_timeout() == 200.0


@pytest.mark.parametrize("bad", ["", "abc", "0", "-5"])
def test_invalid_explicit_setting_falls_back_to_the_computed_value(three_providers, monkeypatch, bad):
    monkeypatch.setenv("JUDGE_SERVICE_TIMEOUT", bad)
    assert router_service.judge_call_timeout() == 95.0


@pytest.mark.parametrize("judge_llm, fallback, chain", [(60, 10, 3), (30, 20, 2), (120, 45, 3), (15, 5, 1)])
def test_router_always_waits_longer_than_the_judge_can_take(monkeypatch, judge_llm, fallback, chain):
    monkeypatch.setenv("JUDGE_LLM_TIMEOUT", str(judge_llm))
    with patch.object(router_service.llm_client, "providers", ["p"] * chain), \
         patch.object(router_service.llm_client, "fallback_timeout", float(fallback)):
        worst_case_of_the_judge = judge_llm + (chain - 1) * fallback
        assert router_service.judge_call_timeout() > worst_case_of_the_judge


def test_call_judge_uses_the_computed_timeout(three_providers):
    with patch("src.services.router_service.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = MagicMock(json=MagicMock(return_value={"ok": True}))
        router_service._call_judge("http://judge-service:8000/judge", {"claim": "x"})
    assert client_cls.call_args.kwargs["timeout"] == 95.0
