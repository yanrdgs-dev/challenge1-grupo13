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


# ------------------ propagação entre serviços (W3C traceparent) ------------------ #

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
SPAN_ID = "b7ad6b7169203331"
VALID = f"00-{TRACE_ID}-{SPAN_ID}-01"


def test_traceparent_header_is_empty_when_disabled(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    with patch.object(tracing, "_get_client") as getter:
        assert tracing.traceparent_header() == {}
    getter.assert_not_called()


def test_traceparent_header_from_current_span(client):
    client.get_current_trace_id.return_value = TRACE_ID
    client.get_current_observation_id.return_value = SPAN_ID
    assert tracing.traceparent_header() == {"traceparent": VALID}


@pytest.mark.parametrize("trace_id, span_id", [(None, SPAN_ID), (TRACE_ID, None), (None, None)])
def test_traceparent_header_is_empty_without_active_span(client, trace_id, span_id):
    client.get_current_trace_id.return_value = trace_id
    client.get_current_observation_id.return_value = span_id
    assert tracing.traceparent_header() == {}


def test_traceparent_header_swallows_client_errors(enabled):
    with patch.object(tracing, "_get_client", side_effect=Exception("sem rede")):
        assert tracing.traceparent_header() == {}


def test_parse_traceparent_valid():
    assert tracing.parse_traceparent(VALID) == {"trace_id": TRACE_ID, "parent_span_id": SPAN_ID}


@pytest.mark.parametrize("value", [
    None, "", "lixo", "00-abc-def-01",
    f"00-{'0' * 32}-{SPAN_ID}-01",           # trace_id zerado é inválido no W3C
    f"00-{TRACE_ID}-{'0' * 16}-01",          # span_id zerado
    f"00-{TRACE_ID.upper()}-{SPAN_ID}-01",   # W3C exige hexadecimal minúsculo
    f"ff-{TRACE_ID}-{SPAN_ID}-01",           # versão ff é proibida
    f"00-{TRACE_ID}-{SPAN_ID}",              # faltam as flags
])
def test_parse_traceparent_invalid_returns_none(value):
    assert tracing.parse_traceparent(value) is None


def test_observation_continues_trace_from_valid_traceparent(client):
    with tracing.observation("judge.evaluate", traceparent=VALID):
        pass
    client.start_as_current_observation.assert_called_once_with(
        name="judge.evaluate",
        as_type="span",
        trace_context={"trace_id": TRACE_ID, "parent_span_id": SPAN_ID},
    )


def test_observation_ignores_invalid_traceparent(client):
    with tracing.observation("judge.evaluate", traceparent="lixo"):
        pass
    client.start_as_current_observation.assert_called_once_with(name="judge.evaluate", as_type="span")


def test_observation_without_traceparent_is_unchanged(client):
    with tracing.observation("x", traceparent=None):
        pass
    client.start_as_current_observation.assert_called_once_with(name="x", as_type="span")


# ------------------------------ release (GIT_SHA) ------------------------------ #

def test_release_prefers_git_sha(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.setenv("LANGFUSE_RELEASE", "outro")
    assert tracing.release() == "abc1234"


def test_release_falls_back_to_langfuse_release_then_none(monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.setenv("LANGFUSE_RELEASE", "v1")
    assert tracing.release() == "v1"
    monkeypatch.delenv("LANGFUSE_RELEASE")
    assert tracing.release() is None


def test_get_client_maps_git_sha_to_langfuse_release(enabled, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.delenv("LANGFUSE_RELEASE", raising=False)
    seen = {}

    def fake_get_client():
        import os
        seen["release"] = os.environ.get("LANGFUSE_RELEASE")
        return MagicMock()

    with patch("langfuse.get_client", fake_get_client):
        tracing._get_client()
    assert seen["release"] == "abc1234"
    monkeypatch.delenv("LANGFUSE_RELEASE", raising=False)


def test_get_client_does_not_override_explicit_langfuse_release(enabled, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.setenv("LANGFUSE_RELEASE", "explicito")
    with patch("langfuse.get_client", return_value=MagicMock()):
        tracing._get_client()
    import os
    assert os.environ["LANGFUSE_RELEASE"] == "explicito"
