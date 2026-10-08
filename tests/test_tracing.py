"""Testes do wrapper de tracing: no-op quando desligado e nunca derruba a request."""

from unittest.mock import MagicMock, patch

import pytest

from src.observability import tracing


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-teste")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-teste")


@pytest.fixture
def client(enabled):
    """Client do Langfuse mockado; devolve (client, observation)."""
    obs = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = obs
    cm.__exit__.return_value = False
    mock_client = MagicMock()
    mock_client.start_as_current_observation.return_value = cm
    with patch.object(tracing, "_get_client", return_value=mock_client) as getter:
        mock_client._getter = getter
        mock_client._obs = obs
        mock_client._cm = cm
        yield mock_client


# ------------------------------ desligado ------------------------------ #

def test_disabled_by_flag_makes_zero_langfuse_calls(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-teste")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-teste")
    with patch.object(tracing, "_get_client") as getter:
        with tracing.observation("check_claim") as obs:
            obs.update(output="x")
            assert obs.trace_id is None
        tracing.flush()
        assert tracing.current_trace_id() is None
    getter.assert_not_called()
    assert tracing.is_enabled() is False


@pytest.mark.parametrize("missing", ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"])
def test_disabled_without_keys(monkeypatch, missing):
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-teste")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-teste")
    monkeypatch.delenv(missing)
    with patch.object(tracing, "_get_client") as getter:
        with tracing.observation("x"):
            pass
    getter.assert_not_called()
    assert tracing.is_enabled() is False


def test_body_result_and_exceptions_are_preserved_when_disabled(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    with pytest.raises(ValueError, match="erro do corpo"):
        with tracing.observation("x"):
            raise ValueError("erro do corpo")


# ------------------------------- ligado -------------------------------- #

def test_enabled_opens_observation_with_arguments(client):
    with tracing.observation("router", as_type="generation", model="qwen2.5:7b", input="claim") as obs:
        obs.update(output="ok", usage_details={"input": 1, "output": 2})

    client.start_as_current_observation.assert_called_once_with(
        name="router", as_type="generation", model="qwen2.5:7b", input="claim"
    )
    client._obs.update.assert_called_once_with(output="ok", usage_details={"input": 1, "output": 2})
    client._cm.__exit__.assert_called_once_with(None, None, None)


def test_trace_id_comes_from_observation(client):
    client._obs.trace_id = "abc123"
    with tracing.observation("x") as obs:
        assert obs.trace_id == "abc123"


def test_current_trace_id_delegates_to_client(client):
    client.get_current_trace_id.return_value = "trace-9"
    assert tracing.current_trace_id() == "trace-9"


def test_body_exception_propagates_and_reaches_exit(client):
    with pytest.raises(RuntimeError, match="boom"):
        with tracing.observation("x"):
            raise RuntimeError("boom")
    exc_type = client._cm.__exit__.call_args[0][0]
    assert exc_type is RuntimeError


# ------------------- Langfuse falhando nunca derruba a request ------------------- #

def test_error_opening_observation_does_not_break_body(client):
    client.start_as_current_observation.side_effect = Exception("langfuse fora do ar")
    ran = []
    with tracing.observation("x") as obs:
        obs.update(output="x")
        ran.append(True)
    assert ran == [True]


def test_error_getting_client_does_not_break_body(enabled):
    with patch.object(tracing, "_get_client", side_effect=Exception("sem rede")):
        with tracing.observation("x") as obs:
            obs.update(output="x")
        tracing.flush()
        assert tracing.current_trace_id() is None


def test_error_in_update_is_swallowed(client):
    client._obs.update.side_effect = Exception("falha no update")
    with tracing.observation("x") as obs:
        obs.update(output="x")


def test_error_in_exit_is_swallowed(client):
    client._cm.__exit__.side_effect = Exception("falha ao fechar")
    with tracing.observation("x"):
        pass


def test_flush_calls_client_and_swallows_errors(client):
    tracing.flush()
    client.flush.assert_called_once()
    client.flush.side_effect = Exception("timeout")
    tracing.flush()


def test_shutdown_calls_client_and_swallows_errors(client):
    tracing.shutdown()
    client.shutdown.assert_called_once()
    client.shutdown.side_effect = Exception("timeout")
    tracing.shutdown()
