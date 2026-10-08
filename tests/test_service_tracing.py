"""Estrutura dos traces gerados pelo router e pelo judge (spans aninhados)."""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.core.llm_client import ChatResult
from src.services import judge_service, router_service

router_client = TestClient(router_service.app)
judge_client = TestClient(judge_service.app)

CLAIM = "O deputado Fulano de Tal é do PL-SP."
JUDGE_OK = {
    "veredito": "VERDADEIRO",
    "confianca": "ALTA",
    "justificativa": "Conforme a Câmara dos Deputados, confirmado.",
    "fontes_primarias": ["Câmara dos Deputados"],
    "tempo_julgamento_ms": 5.0,
}


def _router_chat(tool_calls):
    return ChatResult(content="", tool_calls=tool_calls, provider="ollama", model="qwen2.5:7b")


# ------------------------------- router ------------------------------- #

def test_router_full_flow_trace_structure(trace_recorder):
    chat = _router_chat([{"name": "resolve_politician", "arguments": {"nome_busca": "Fulano"}}])
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "execute_tool", return_value={"ideCadastro": 1}), \
         patch.object(router_service, "_call_judge", return_value=JUDGE_OK):
        llm.chat.return_value = chat
        resp = router_client.post("/check", json={"claim": CLAIM})

    assert resp.status_code == 200
    assert trace_recorder.tree() == [
        ("check_claim", None),
        ("guardrails.input", "check_claim"),
        ("tool.resolve_politician", "check_claim"),
        ("judge.call", "check_claim"),
        ("guardrails.output", "check_claim"),
    ]


def test_router_root_span_records_claim_and_final_result(trace_recorder):
    chat = _router_chat([{"name": "resolve_politician", "arguments": {"nome_busca": "Fulano"}}])
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "execute_tool", return_value={"ideCadastro": 1}), \
         patch.object(router_service, "_call_judge", return_value=JUDGE_OK):
        llm.chat.return_value = chat
        router_client.post("/check", json={"claim": CLAIM})

    assert trace_recorder.get("check_claim")["kwargs"]["input"] == CLAIM
    assert trace_recorder.merged_updates("check_claim")["output"]["veredito"] == "VERDADEIRO"


def test_input_rail_block_records_span_and_stops_the_flow(trace_recorder):
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "_call_judge") as judge:
        resp = router_client.post(
            "/check", json={"claim": "Um deputado gastou muito dinheiro público recentemente."}
        )

    assert resp.json()["veredito"] == "INCONCLUSIVO"
    assert trace_recorder.tree() == [("check_claim", None), ("guardrails.input", "check_claim")]
    update = trace_recorder.merged_updates("guardrails.input")
    assert update["output"]["blocked"] is True
    assert update["output"]["rule_matched"] == "guarda_de_especificidade"
    llm.chat.assert_not_called()
    judge.assert_not_called()


def test_tool_span_records_arguments_and_evidence(trace_recorder):
    chat = _router_chat([{"name": "resolve_politician", "arguments": {"nome_busca": "Fulano"}}])
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "execute_tool", return_value={"ideCadastro": 1}), \
         patch.object(router_service, "_call_judge", return_value=JUDGE_OK):
        llm.chat.return_value = chat
        router_client.post("/check", json={"claim": CLAIM})

    tool = trace_recorder.get("tool.resolve_politician")
    assert tool["kwargs"]["input"] == {"nome_busca": "Fulano"}
    assert trace_recorder.merged_updates("tool.resolve_politician")["output"] == {"ideCadastro": 1}


def test_no_tool_chosen_has_no_tool_span(trace_recorder):
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "_call_judge", return_value=JUDGE_OK):
        llm.chat.return_value = _router_chat([])
        router_client.post("/check", json={"claim": CLAIM})

    assert not [n for n, _ in trace_recorder.tree() if n.startswith("tool.")]


def test_tool_error_is_recorded_and_flow_continues(trace_recorder):
    chat = _router_chat([{"name": "resolve_politician", "arguments": {"nome_busca": "Fulano"}}])
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "execute_tool", side_effect=RuntimeError("duckdb falhou")), \
         patch.object(router_service, "_call_judge", return_value=JUDGE_OK):
        llm.chat.return_value = chat
        resp = router_client.post("/check", json={"claim": CLAIM})

    assert resp.status_code == 200
    update = trace_recorder.merged_updates("tool.resolve_politician")
    assert update["level"] == "ERROR"
    assert "duckdb falhou" in update["status_message"]


def test_output_rail_override_is_recorded(trace_recorder):
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "_call_judge", return_value={**JUDGE_OK, "veredito": "FALSO"}):
        llm.chat.return_value = _router_chat([])  # sem tool
        resp = router_client.post("/check", json={"claim": CLAIM})

    assert resp.json()["veredito"] == "INCONCLUSIVO"
    out = trace_recorder.merged_updates("guardrails.output")["output"]
    assert out["passed"] is False
    assert out["verdict_before"] == "FALSO"
    assert out["final_verdict"] == "INCONCLUSIVO"


def test_judge_call_span_records_verdict_and_failure(trace_recorder):
    chat = _router_chat([{"name": "resolve_politician", "arguments": {"nome_busca": "Fulano"}}])
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "execute_tool", return_value={"ideCadastro": 1}), \
         patch.object(router_service, "_call_judge", side_effect=Exception("judge fora do ar")):
        llm.chat.return_value = chat
        router_client.post("/check", json={"claim": CLAIM})

    update = trace_recorder.merged_updates("judge.call")
    assert update["level"] == "ERROR"
    assert "judge fora do ar" in update["status_message"]


def test_resolver_chosen_as_tool_has_single_span_without_duplicate_child(trace_recorder):
    """tool.<nome> já representa o resolver escolhido; não há span interno duplicado."""
    chat = _router_chat([{"name": "resolve_politician", "arguments": {"nome_busca": "Fulano"}}])
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "resolve_politician", return_value={"ideCadastro": 7}), \
         patch.object(router_service, "_call_judge", return_value=JUDGE_OK):
        llm.chat.return_value = chat
        router_client.post("/check", json={"claim": CLAIM})

    names = [n for n, _ in trace_recorder.tree()]
    assert names.count("tool.resolve_politician") == 1
    assert "resolve_politician" not in names
    assert trace_recorder.merged_updates("tool.resolve_politician")["output"] == {"ideCadastro": 7}


def test_any_chosen_tool_gets_a_tool_span(trace_recorder):
    """Tools de dados (não resolvers) também ganham o span tool.<nome>."""
    chat = _router_chat([{"name": "check_parliamentary_expenses", "arguments": {"ano": 2023}}])
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "execute_tool", return_value={"total": 10.0}), \
         patch.object(router_service, "_call_judge", return_value=JUDGE_OK):
        llm.chat.return_value = chat
        router_client.post("/check", json={"claim": CLAIM})

    assert ("tool.check_parliamentary_expenses", "check_claim") in trace_recorder.tree()


# ------------------------------- judge -------------------------------- #

def test_judge_records_evaluate_span_with_verdict(trace_recorder):
    result = ChatResult(
        content=json.dumps({"veredito": "FALSO", "confianca": "ALTA", "justificativa": "x", "fontes_primarias": ["TSE"]}),
        provider="ollama",
        model="qwen2.5:14b",
    )
    with patch.object(judge_service, "llm_client") as llm:
        llm.chat.return_value = result
        resp = judge_client.post(
            "/judge",
            json={"claim": "c", "evidence": {"a": 1}, "tool_used": "resolve_politician"},
        )

    assert resp.status_code == 200
    assert trace_recorder.tree() == [("judge.evaluate", None)]
    span = trace_recorder.get("judge.evaluate")
    assert span["kwargs"]["input"]["tool_used"] == "resolve_politician"
    assert trace_recorder.merged_updates("judge.evaluate")["output"]["veredito"] == "FALSO"


# ------------------------- propagação router -> judge ------------------------- #

TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


def test_router_sends_traceparent_to_judge(trace_recorder):
    chat = _router_chat([{"name": "resolve_politician", "arguments": {"nome_busca": "Fulano"}}])
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "execute_tool", return_value={"ideCadastro": 1}), \
         patch("src.observability.tracing.traceparent_header", return_value={"traceparent": TRACEPARENT}), \
         patch.object(router_service, "_call_judge", return_value=JUDGE_OK) as judge:
        llm.chat.return_value = chat
        router_client.post("/check", json={"claim": CLAIM})

    assert judge.call_args.kwargs["headers"] == {"traceparent": TRACEPARENT}


def test_call_judge_forwards_headers_over_http():
    resp = MagicMock()
    resp.json.return_value = JUDGE_OK
    with patch("httpx.Client.post", return_value=resp) as post:
        out = router_service._call_judge("http://judge/judge", {"claim": "c"}, headers={"traceparent": TRACEPARENT})

    assert out == JUDGE_OK
    assert post.call_args.kwargs["headers"] == {"traceparent": TRACEPARENT}


def test_judge_continues_trace_from_traceparent_header(trace_recorder):
    result = ChatResult(content=json.dumps({"veredito": "FALSO", "fontes_primarias": ["TSE"]}),
                        provider="ollama", model="qwen2.5:14b")
    with patch.object(judge_service, "llm_client") as llm:
        llm.chat.return_value = result
        judge_client.post(
            "/judge",
            json={"claim": "c", "evidence": {"a": 1}, "tool_used": "resolve_politician"},
            headers={"traceparent": TRACEPARENT},
        )

    assert trace_recorder.get("judge.evaluate")["kwargs"]["traceparent"] == TRACEPARENT


def test_judge_without_header_starts_its_own_trace(trace_recorder):
    result = ChatResult(content="{}", provider="ollama", model="qwen2.5:14b")
    with patch.object(judge_service, "llm_client") as llm:
        llm.chat.return_value = result
        judge_client.post("/judge", json={"claim": "c"})

    assert trace_recorder.get("judge.evaluate")["kwargs"]["traceparent"] is None


def test_router_to_judge_end_to_end_shares_the_same_traceparent(trace_recorder):
    """Simula a chamada HTTP: o header que o router envia é o que o judge recebe."""
    chat = _router_chat([{"name": "resolve_politician", "arguments": {"nome_busca": "Fulano"}}])
    judge_llm = ChatResult(content=json.dumps({"veredito": "VERDADEIRO", "fontes_primarias": ["TSE"],
                                               "justificativa": "TSE confirma."}),
                           provider="ollama", model="qwen2.5:14b")

    def fake_call_judge(endpoint, payload, headers=None):
        return judge_client.post("/judge", json=payload, headers=headers or {}).json()

    with patch.object(router_service, "llm_client") as router_llm, \
         patch.object(judge_service, "llm_client") as judge_llm_client, \
         patch.object(router_service, "execute_tool", return_value={"ideCadastro": 1}), \
         patch("src.observability.tracing.traceparent_header", return_value={"traceparent": TRACEPARENT}), \
         patch.object(router_service, "_call_judge", side_effect=fake_call_judge):
        router_llm.chat.return_value = chat
        judge_llm_client.chat.return_value = judge_llm
        resp = router_client.post("/check", json={"claim": CLAIM})

    assert resp.json()["veredito"] == "VERDADEIRO"
    assert trace_recorder.get("judge.evaluate")["kwargs"]["traceparent"] == TRACEPARENT


# ---------------------- trace_id, veredito, tool e release ---------------------- #

def _run_full_check(trace_recorder_arg=None):
    chat = _router_chat([{"name": "resolve_politician", "arguments": {"nome_busca": "Fulano"}}])
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "execute_tool", return_value={"ideCadastro": 1}), \
         patch.object(router_service, "_call_judge", return_value=JUDGE_OK):
        llm.chat.return_value = chat
        return router_client.post("/check", json={"claim": CLAIM})


def test_response_exposes_trace_id_from_root_span(trace_recorder):
    trace_recorder.trace_id = "0af7651916cd43dd8448eb211c80319c"
    resp = _run_full_check()
    assert resp.json()["trace_id"] == "0af7651916cd43dd8448eb211c80319c"


def test_trace_id_is_null_when_tracing_is_off():
    resp = _run_full_check()  # sem trace_recorder: tracing desligado pelo conftest
    assert "trace_id" in resp.json()
    assert resp.json()["trace_id"] is None


def test_input_rail_block_response_also_carries_trace_id(trace_recorder):
    trace_recorder.trace_id = "t-bloqueio"
    resp = router_client.post(
        "/check", json={"claim": "Um deputado gastou muito dinheiro público recentemente."}
    )
    assert resp.json()["veredito"] == "INCONCLUSIVO"
    assert resp.json()["trace_id"] == "t-bloqueio"


def test_root_span_records_verdict_tool_and_release(trace_recorder, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc1234")
    _run_full_check()
    metadata = trace_recorder.merged_updates("check_claim")["metadata"]
    assert metadata == {"veredito": "VERDADEIRO", "tool_usada": "resolve_politician", "release": "abc1234"}


def test_root_span_metadata_for_blocked_claim_has_no_tool(trace_recorder, monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("LANGFUSE_RELEASE", raising=False)
    router_client.post("/check", json={"claim": "Um deputado gastou muito dinheiro público recentemente."})
    metadata = trace_recorder.merged_updates("check_claim")["metadata"]
    assert metadata == {"veredito": "INCONCLUSIVO", "tool_usada": None, "release": None}
