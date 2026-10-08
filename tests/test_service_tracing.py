"""Estrutura dos traces gerados pelo router e pelo judge (spans aninhados)."""

import json
from unittest.mock import patch

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


def test_resolve_span_wraps_the_resolver_inside_execute_tool(trace_recorder):
    with patch.object(router_service, "resolve_politician", return_value={"ideCadastro": 7}):
        evidence = router_service.execute_tool("resolve_politician", {"nome_busca": "Fulano"})

    assert evidence == {"ideCadastro": 7}
    assert trace_recorder.tree() == [("resolve_politician", None)]
    assert trace_recorder.get("resolve_politician")["kwargs"]["input"] == {"nome_busca": "Fulano"}
    assert trace_recorder.merged_updates("resolve_politician")["output"] == {"ideCadastro": 7}


def test_resolve_proposition_span(trace_recorder):
    with patch.object(router_service, "resolve_proposition", return_value={"id": 5}):
        router_service.execute_tool("resolve_proposition", {"sigla_tipo": "PL", "numero": 1, "ano": 2023})

    assert trace_recorder.tree() == [("resolve_proposition", None)]


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
