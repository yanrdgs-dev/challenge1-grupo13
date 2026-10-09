"""get_prompt: prompt do Langfuse com cache e fallback local (nunca derruba a request)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.observability import prompts
from src.observability.prompts import PromptResult, compile_template, get_prompt

LOCAL = "Olá {{nome}}, a claim é: {{claim}}."


@pytest.fixture(autouse=True)
def reset_state():
    prompts._failed_until.clear()
    yield
    prompts._failed_until.clear()


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-teste")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-teste")
    monkeypatch.delenv("LANGFUSE_PROMPT_LABEL", raising=False)
    monkeypatch.delenv("PROMPT_CACHE_TTL_SECONDS", raising=False)


def remote(text="Remoto {{claim}}", version=3, is_fallback=False):
    client = MagicMock()
    client.version = version
    client.is_fallback = is_fallback
    client.labels = ["production"]
    client.compile.side_effect = lambda **kw: text.replace("{{claim}}", str(kw.get("claim", "")))
    return client


@pytest.fixture
def lf(enabled):
    client = MagicMock()
    client.get_prompt.return_value = remote()
    with patch.object(prompts, "_get_client", return_value=client):
        yield client


# --------------------------------- compile local --------------------------------- #

def test_compile_template_replaces_variables():
    assert compile_template(LOCAL, {"nome": "Ana", "claim": "X"}) == "Olá Ana, a claim é: X."


def test_compile_template_tolerates_spaces_and_non_strings():
    assert compile_template("{{ n }} e {{n}}", {"n": 5}) == "5 e 5"


def test_compile_template_keeps_unknown_variables_and_single_braces():
    assert compile_template('{"a": 1} {{falta}}', {}) == '{"a": 1} {{falta}}'


def test_compile_template_is_not_recursive():
    """Um valor com {{...}} (ex.: evidência vinda de dado externo) não é reinterpretado."""
    assert compile_template("{{a}}", {"a": "{{b}}", "b": "X"}) == "{{b}}"


# -------------------------------------- local -------------------------------------- #

def test_tracing_disabled_uses_local_prompt_with_zero_calls(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    with patch.object(prompts, "_get_client") as getter:
        result = get_prompt("p", LOCAL, {"nome": "Ana", "claim": "X"})
    getter.assert_not_called()
    assert result == PromptResult(text="Olá Ana, a claim é: X.", name="p", version=None,
                                  label="production", source="local", prompt_client=None)


# -------------------------------------- remoto -------------------------------------- #

def test_remote_prompt_is_fetched_with_label_cache_and_local_fallback(lf):
    result = get_prompt("p", LOCAL, {"claim": "X"})
    lf.get_prompt.assert_called_once_with(
        "p", label="production", type="text", fallback=LOCAL,
        cache_ttl_seconds=60, max_retries=0, fetch_timeout_seconds=2,
    )
    assert result.source == "langfuse" and result.version == 3 and result.text == "Remoto X"
    assert result.prompt_client is lf.get_prompt.return_value


def test_label_comes_from_env_for_experiments(lf, monkeypatch):
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "staging")
    result = get_prompt("p", LOCAL, {"claim": "X"})
    assert lf.get_prompt.call_args.kwargs["label"] == "staging" and result.label == "staging"


def test_explicit_label_overrides_env(lf, monkeypatch):
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "staging")
    assert get_prompt("p", LOCAL, label="production").label == "production"


def test_cache_ttl_comes_from_env(lf, monkeypatch):
    monkeypatch.setenv("PROMPT_CACHE_TTL_SECONDS", "300")
    get_prompt("p", LOCAL)
    assert lf.get_prompt.call_args.kwargs["cache_ttl_seconds"] == 300


def test_sdk_fallback_client_is_reported_as_local(lf):
    lf.get_prompt.return_value = remote(is_fallback=True)
    result = get_prompt("p", LOCAL, {"nome": "Ana", "claim": "X"})
    assert result.source == "local" and result.prompt_client is None
    assert result.text == "Olá Ana, a claim é: X."          # texto local, não o do cliente de fallback


# ----------------------------- Langfuse fora do ar ----------------------------- #

def test_fetch_error_falls_back_to_local(lf):
    lf.get_prompt.side_effect = Exception("timeout")
    result = get_prompt("p", LOCAL, {"nome": "Ana", "claim": "X"})
    assert result.source == "local" and result.text == "Olá Ana, a claim é: X."


def test_client_creation_error_falls_back_to_local(enabled):
    with patch.object(prompts, "_get_client", side_effect=Exception("sem rede")):
        assert get_prompt("p", LOCAL, {"nome": "A", "claim": "X"}).source == "local"


def test_compile_error_falls_back_to_local(lf):
    lf.get_prompt.return_value.compile.side_effect = Exception("variável faltando")
    result = get_prompt("p", LOCAL, {"nome": "Ana", "claim": "X"})
    assert result.source == "local" and result.text == "Olá Ana, a claim é: X."


def test_after_a_failure_the_next_calls_skip_langfuse_for_a_while(lf):
    """Evita pagar o timeout em toda request enquanto o Langfuse está fora do ar."""
    lf.get_prompt.side_effect = Exception("timeout")
    get_prompt("p", LOCAL)
    get_prompt("p", LOCAL)
    get_prompt("p", LOCAL)
    assert lf.get_prompt.call_count == 1


def test_langfuse_is_retried_after_the_backoff_window(lf):
    lf.get_prompt.side_effect = Exception("timeout")
    with patch.object(prompts.time, "monotonic", return_value=1000.0):
        get_prompt("p", LOCAL)
    lf.get_prompt.side_effect = None
    lf.get_prompt.return_value = remote()
    with patch.object(prompts.time, "monotonic", return_value=1000.0 + prompts.FAILURE_BACKOFF_SECONDS + 1):
        result = get_prompt("p", LOCAL, {"claim": "X"})
    assert result.source == "langfuse"


def test_failure_of_one_prompt_does_not_block_another(lf):
    lf.get_prompt.side_effect = [Exception("timeout"), remote()]
    get_prompt("a", LOCAL)
    assert get_prompt("b", LOCAL, {"claim": "X"}).source == "langfuse"
