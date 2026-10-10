"""Modelo por papel (roteador e juiz) nos provedores de nuvem.

`ROUTER_GROQ_MODEL` / `JUDGE_GROQ_MODEL` (e o mesmo para DEEPSEEK e OPENAI) sobrescrevem `GROQ_MODEL` etc.
Na Groq o limite de uso é por modelo: papéis com modelos diferentes têm cotas separadas.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.core.llm_client import LLMClient

MESSAGES = [{"role": "user", "content": "oi"}]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in (
        "LLM_PROVIDERS", "LLM_PROVIDER", "FALLBACK_PROVIDER",
        "GROQ_MODEL", "DEEPSEEK_MODEL", "OPENAI_MODEL",
        "ROUTER_GROQ_MODEL", "JUDGE_GROQ_MODEL", "ROUTER_DEEPSEEK_MODEL", "JUDGE_DEEPSEEK_MODEL",
        "ROUTER_OPENAI_MODEL", "JUDGE_OPENAI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")


def requested_model(provider, role=None):
    """Modelo enviado no corpo da requisição ao provedor de nuvem."""
    captured = {}

    def fake_post(url, *args, **kwargs):
        captured["model"] = kwargs["json"]["model"]
        resp = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
        return resp

    with patch("httpx.Client.post", side_effect=fake_post):
        LLMClient(providers=[provider], role=role).chat(MESSAGES)
    return captured["model"]


def test_role_model_overrides_the_provider_model(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("ROUTER_GROQ_MODEL", "openai/gpt-oss-20b")
    assert requested_model("groq", role="router") == "openai/gpt-oss-20b"


def test_each_role_reads_its_own_variable(monkeypatch):
    monkeypatch.setenv("ROUTER_GROQ_MODEL", "openai/gpt-oss-20b")
    monkeypatch.setenv("JUDGE_GROQ_MODEL", "openai/gpt-oss-120b")
    assert requested_model("groq", role="router") == "openai/gpt-oss-20b"
    assert requested_model("groq", role="judge") == "openai/gpt-oss-120b"


def test_role_without_its_own_variable_uses_the_shared_provider_model(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("ROUTER_GROQ_MODEL", "openai/gpt-oss-20b")
    assert requested_model("groq", role="judge") == "openai/gpt-oss-120b"


def test_without_any_variable_the_provider_default_applies():
    assert requested_model("groq", role="judge") == "llama-3.1-8b-instant"
    assert requested_model("deepseek", role="judge") == "deepseek-flash"


def test_client_without_role_ignores_role_variables(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("ROUTER_GROQ_MODEL", "openai/gpt-oss-20b")
    assert requested_model("groq") == "openai/gpt-oss-120b"


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_role_variable_falls_back_to_the_shared_model(monkeypatch, blank):
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("JUDGE_GROQ_MODEL", blank)
    assert requested_model("groq", role="judge") == "openai/gpt-oss-120b"


def test_role_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("JUDGE_GROQ_MODEL", "openai/gpt-oss-120b")
    assert requested_model("groq", role="Judge") == "openai/gpt-oss-120b"


@pytest.mark.parametrize("provider", ["deepseek", "openai"])
def test_override_works_for_every_openai_compatible_provider(monkeypatch, provider):
    monkeypatch.setenv(f"JUDGE_{provider.upper()}_MODEL", "modelo-do-juiz")
    monkeypatch.setenv(f"{provider.upper()}_MODEL", "modelo-comum")
    assert requested_model(provider, role="judge") == "modelo-do-juiz"
    assert requested_model(provider, role="router") == "modelo-comum"


def test_generate_path_honours_the_role_model_too(monkeypatch):
    monkeypatch.setenv("JUDGE_GROQ_MODEL", "openai/gpt-oss-120b")
    captured = {}

    def fake_post(url, *args, **kwargs):
        captured["model"] = kwargs["json"]["model"]
        resp = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": "texto"}}]}
        return resp

    with patch("httpx.Client.post", side_effect=fake_post):
        assert LLMClient(providers=["groq"], role="judge").generate("pergunta") == "texto"
    assert captured["model"] == "openai/gpt-oss-120b"


def test_ollama_model_still_comes_from_the_call_not_from_role_variables(monkeypatch):
    monkeypatch.setenv("ROUTER_GROQ_MODEL", "openai/gpt-oss-20b")
    captured = {}

    def fake_post(url, *args, **kwargs):
        captured["model"] = kwargs["json"]["model"]
        resp = MagicMock()
        resp.json.return_value = {"message": {"content": "ok"}, "model": "qwen2.5:7b"}
        return resp

    with patch("httpx.Client.post", side_effect=fake_post):
        LLMClient(providers=["ollama"], role="router").chat(MESSAGES, model="qwen2.5:7b")
    assert captured["model"] == "qwen2.5:7b"


def test_trace_generation_records_the_role_model(monkeypatch):
    monkeypatch.setenv("ROUTER_GROQ_MODEL", "openai/gpt-oss-20b")
    seen = {}

    from contextlib import contextmanager

    @contextmanager
    def fake_observation(name, **kwargs):
        seen.update(kwargs)
        yield MagicMock()

    resp = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
    with patch("src.core.llm_client.tracing.observation", fake_observation), \
         patch("httpx.Client.post", return_value=resp):
        LLMClient(providers=["groq"], role="router").chat(MESSAGES)
    assert seen["model"] == "openai/gpt-oss-20b"


def test_services_build_their_clients_with_their_own_role():
    from src.services import judge_service, router_service

    assert router_service.llm_client.role == "router"
    assert judge_service.llm_client.role == "judge"
