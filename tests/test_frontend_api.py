"""Adaptador do frontend no router: /api/health, /api/suggestions, /api/check, /api/check/stream e /api/feedback.

O frontend (Pólis) fala `{query}` → `{id, query, verdict, text, subdetails, sources, rule_matched}`, com
eventos SSE `step`/`token`/`done`. O pipeline continua sendo um só (guardrails → router → tool → judge →
guardrails): estes endpoints só traduzem o contrato e o encadeiam ao /check.
"""

import json
import re
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.core.llm_client import ChatResult
from src.services import router_service
from src.services.router_service import CheckClaimResponse, app
from tests.conftest import SpanRecorder

client = TestClient(app)

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
CLAIM = "O deputado Fulano de Tal é do PL-SP."


def _response(**over):
    base = dict(
        claim=CLAIM, tool_usada="resolve_politician", parametros_tool={"nome_busca": "Fulano"},
        evidencia_coletada={"ideCadastro": 1}, veredito="VERDADEIRO", confianca="ALTA",
        justificativa="Conforme a Câmara dos Deputados - Dados Abertos, a alegação procede.",
        fontes_primarias=["Câmara dos Deputados - Dados Abertos"], tempo_total_ms=1234.5,
        tempo_roteamento_ms=500.0, tempo_julgamento_ms=700.0,
        ferramentas_usadas=["resolve_politician"], trace_id=TRACE_ID,
    )
    base.update(over)
    return CheckClaimResponse(**base)


@pytest.fixture
def fake_check():
    """Substitui o pipeline: emite as etapas pedidas e devolve a resposta configurada."""
    recorder = SpanRecorder(trace_id=TRACE_ID)
    state = {"response": _response(), "steps": ("tools", "search", "synthesis"), "error": None, "claims": [],
             "recorder": recorder}

    def run(claim_text, start_total, on_step=None):
        state["claims"].append(claim_text)
        if state["error"]:
            raise state["error"]
        for step in state["steps"]:
            if on_step:
                on_step(step)
        return state["response"]

    with patch.object(router_service, "_run_check", side_effect=run), \
         patch("src.observability.tracing.observation", recorder.observation), \
         patch("src.observability.tracing.trace_attributes", recorder.trace_attributes):
        yield state


def parse_sse(text):
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        name, data = "message", ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[7:].strip()
            elif line.startswith("data: "):
                data = line[6:]
        events.append((name, json.loads(data) if data else None))
    return events


# ------------------------------------ health e sugestões ------------------------------------ #

def test_health_is_static_and_does_not_touch_the_llm():
    with patch.object(router_service, "llm_client") as llm:
        resp = client.get("/api/health")
    assert resp.status_code == 200 and resp.json()["status"] == "ok"
    llm.chat.assert_not_called()


def test_suggestions_follow_the_frontend_contract():
    resp = client.get("/api/suggestions")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 4
    for item in items:
        assert set(item) == {"icon", "eyebrow", "text"}
        assert all(isinstance(v, str) and v.strip() for v in item.values())


def test_suggestions_icons_exist_in_the_frontend_icon_set():
    icons = {"ballot", "book", "file", "archive", "calendar", "check", "newspaper", "search", "shield",
             "sparkle", "message", "tool", "link", "external", "alert-triangle", "check-circle"}
    assert {i["icon"] for i in client.get("/api/suggestions").json()} <= icons


# ------------------------------------ /api/check ------------------------------------ #

def test_check_translates_the_pipeline_response_to_the_frontend_contract(fake_check):
    data = client.post("/api/check", json={"query": CLAIM}).json()
    assert data["id"] == TRACE_ID
    assert data["query"] == CLAIM
    assert data["verdict"] == "VERDADEIRO"
    assert data["text"] == fake_check["response"].justificativa
    assert data["sources"] == ["Câmara dos Deputados - Dados Abertos"]
    assert data["rule_matched"] is None
    assert isinstance(data["subdetails"], list) and data["subdetails"]


@pytest.mark.parametrize("verdict", ["VERDADEIRO", "FALSO", "INCONCLUSIVO"])
def test_every_verdict_passes_through_unchanged(fake_check, verdict):
    fake_check["response"] = _response(veredito=verdict)
    assert client.post("/api/check", json={"query": CLAIM}).json()["verdict"] == verdict


def test_text_is_the_judge_justification_untouched_neutral_language(fake_check):
    """Regra 6: o adaptador não reescreve nem enfeita o texto do veredito."""
    fake_check["response"] = _response(veredito="FALSO", justificativa="Texto exato do julgador.")
    assert client.post("/api/check", json={"query": CLAIM}).json()["text"] == "Texto exato do julgador."


def test_subdetails_list_the_tools_and_the_confidence(fake_check):
    fake_check["response"] = _response(ferramentas_usadas=["resolve_proposition", "get_proposition_vote_result"],
                                       confianca="MÉDIA")
    sub = " | ".join(client.post("/api/check", json={"query": CLAIM}).json()["subdetails"])
    assert "resolve_proposition" in sub and "get_proposition_vote_result" in sub
    assert "MÉDIA" in sub or "média" in sub.lower()


def test_id_falls_back_to_a_unique_value_when_tracing_is_off(fake_check):
    fake_check["recorder"].trace_id = None
    first = client.post("/api/check", json={"query": CLAIM}).json()["id"]
    second = client.post("/api/check", json={"query": CLAIM}).json()["id"]
    assert first and second and first != second


def test_rule_matched_is_exposed_when_an_input_rail_blocks(fake_check):
    fake_check["response"] = _response(tool_usada=None, veredito="INCONCLUSIVO", regra_acionada="claim_subespecificada",
                                       fontes_primarias=["Constituição do Agente de Fact-Checking"])
    assert client.post("/api/check", json={"query": CLAIM}).json()["rule_matched"] == "claim_subespecificada"


@pytest.mark.parametrize("body,status", [({"query": "   "}, 400), ({"query": ""}, 400), ({}, 422)])
def test_empty_or_missing_query_is_rejected_before_the_pipeline(fake_check, body, status):
    assert client.post("/api/check", json=body).status_code == status
    assert fake_check["claims"] == []


def test_llm_outage_is_a_503_so_the_frontend_can_show_its_own_message():
    with patch.object(router_service, "llm_client") as llm:
        llm.chat.side_effect = RuntimeError("Falha total nos serviços de LLM")
        assert client.post("/api/check", json={"query": CLAIM}).status_code == 503


def test_session_and_user_ids_reach_the_trace(fake_check):
    client.post("/api/check", json={"query": CLAIM, "session_id": "chat-1", "user_id": "u-9"})
    assert fake_check["recorder"].trace_attrs == [{"user_id": "u-9", "session_id": "chat-1"}]


def test_request_without_ids_still_works(fake_check):
    assert client.post("/api/check", json={"query": CLAIM}).status_code == 200


# ------------------------------------ /api/check/stream ------------------------------------ #

def test_stream_uses_server_sent_events_without_proxy_buffering(fake_check):
    resp = client.post("/api/check/stream", json={"query": CLAIM})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"


def test_stream_emits_steps_then_tokens_then_done(fake_check):
    events = parse_sse(client.post("/api/check/stream", json={"query": CLAIM}).text)
    names = [n for n, _ in events]
    assert [d["step"] for n, d in events if n == "step"] == ["tools", "search", "synthesis"]
    assert names.index("step") < names.index("token") < names.index("done")
    assert names[-1] == "done" and names.count("done") == 1


def test_step_events_carry_a_message_for_the_loading_indicator(fake_check):
    for name, data in parse_sse(client.post("/api/check/stream", json={"query": CLAIM}).text):
        if name == "step":
            assert data["message"].strip()


def test_tokens_rebuild_the_justification_exactly(fake_check):
    events = parse_sse(client.post("/api/check/stream", json={"query": CLAIM}).text)
    streamed = "".join(d["token"] for n, d in events if n == "token")
    assert streamed == fake_check["response"].justificativa


def test_done_event_has_the_same_contract_as_the_plain_endpoint(fake_check):
    events = parse_sse(client.post("/api/check/stream", json={"query": CLAIM}).text)
    done = dict(events)["done"]
    plain = client.post("/api/check", json={"query": CLAIM}).json()
    assert set(done) == set(plain)
    assert done["verdict"] == "VERDADEIRO" and done["id"] == TRACE_ID and done["query"] == CLAIM


def test_blocked_claim_streams_straight_to_done(fake_check):
    fake_check["steps"] = ()
    fake_check["response"] = _response(tool_usada=None, veredito="INCONCLUSIVO", regra_acionada="rumor")
    events = parse_sse(client.post("/api/check/stream", json={"query": CLAIM}).text)
    assert not [n for n, _ in events if n == "step"]
    assert dict(events)["done"]["rule_matched"] == "rumor"


def test_pipeline_failure_ends_with_a_clear_inconclusive_done_instead_of_a_dead_stream(fake_check):
    """A resposta HTTP já começou: sem `done` o frontend ficaria sem mensagem e refaria a checagem inteira."""
    fake_check["error"] = RuntimeError("Ollama fora do ar")
    events = parse_sse(client.post("/api/check/stream", json={"query": CLAIM}).text)
    done = dict(events)["done"]
    assert done["verdict"] == "INCONCLUSIVO"
    assert done["rule_matched"] == "servico_indisponivel"
    assert "indisponível" in done["text"].lower()
    assert "Ollama" not in done["text"], "o erro técnico não vaza para o usuário"


def test_stream_rejects_an_empty_query_with_a_real_http_error(fake_check):
    assert client.post("/api/check/stream", json={"query": "  "}).status_code == 400
    assert fake_check["claims"] == []


def test_stream_forwards_session_and_user_ids(fake_check):
    client.post("/api/check/stream", json={"query": CLAIM, "session_id": "chat-7"})
    assert fake_check["recorder"].trace_attrs[0]["session_id"] == "chat-7"


# ------------------------------------ pipeline real: etapas ------------------------------------ #

def _routing_llm():
    from src.tools.knowledge_tools import INSTITUTIONAL_TOPICS
    topic = list(INSTITUTIONAL_TOPICS)[0]
    return ChatResult(content="", tool_calls=[{"name": "check_institutional_rule", "arguments": {"topico": topic}}],
                      usage={}, provider="ollama", model="qwen2.5:7b")


JUDGE = {"veredito": "VERDADEIRO", "confianca": "ALTA", "fontes_primarias": ["Regimento"],
         "justificativa": "Conforme a base normativa curada, procede.", "tempo_julgamento_ms": 5.0}


def test_real_pipeline_reports_tools_then_search_then_synthesis():
    seen = []
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "_call_judge", return_value=JUDGE):
        llm.chat.return_value = _routing_llm()
        router_service._run_check(CLAIM, 0.0, on_step=seen.append)
    assert seen == ["tools", "search", "synthesis"]


def test_real_pipeline_blocked_claim_reports_no_steps_and_the_rule():
    seen = []
    claim = "Um deputado gastou muito dinheiro público recentemente."
    with patch.object(router_service, "llm_client") as llm:
        resp = router_service._run_check(claim, 0.0, on_step=seen.append)
    assert seen == [] and resp.veredito == "INCONCLUSIVO"
    assert resp.regra_acionada
    llm.chat.assert_not_called()


def test_check_endpoint_exposes_the_triggered_rule():
    claim = "Um deputado gastou muito dinheiro público recentemente."
    with patch.object(router_service, "llm_client"):
        data = client.post("/check", json={"claim": claim}).json()
    assert data["regra_acionada"]


def test_regular_claims_have_no_triggered_rule():
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "_call_judge", return_value=JUDGE):
        llm.chat.return_value = _routing_llm()
        data = client.post("/check", json={"claim": CLAIM}).json()
    assert data["regra_acionada"] is None


# ------------------------------------ /api/feedback ------------------------------------ #

@pytest.fixture
def scored():
    with patch("src.observability.tracing.score_trace_by_id", return_value=True) as score:
        yield score


def test_positive_feedback_scores_the_trace(scored):
    resp = client.post("/api/feedback", json={"message_id": TRACE_ID, "rating": "positive", "verdict": "VERDADEIRO"})
    assert resp.status_code == 202 and resp.json()["registrado"] is True
    kwargs = scored.call_args.kwargs
    assert kwargs["trace_id"] == TRACE_ID and kwargs["value"] == "positive"
    assert kwargs["name"] == "feedback_usuario"


def test_negative_feedback_keeps_reason_and_comment(scored):
    client.post("/api/feedback", json={"message_id": TRACE_ID, "rating": "negative", "verdict": "FALSO",
                                       "reason": "Veredito equivocado", "comment": "A fonte está desatualizada."})
    comment = scored.call_args.kwargs["comment"]
    assert "Veredito equivocado" in comment and "desatualizada" in comment


def test_comment_is_truncated_to_a_safe_size(scored):
    client.post("/api/feedback", json={"message_id": TRACE_ID, "rating": "negative", "comment": "x" * 5000})
    assert len(scored.call_args.kwargs["comment"]) <= 1200


@pytest.mark.parametrize("body", [
    {"message_id": TRACE_ID, "rating": "talvez"},
    {"message_id": TRACE_ID},
    {"rating": "positive"},
    {"message_id": "", "rating": "positive"},
])
def test_invalid_feedback_is_rejected(scored, body):
    assert client.post("/api/feedback", json=body).status_code == 422
    scored.assert_not_called()


def test_message_ids_that_are_not_trace_ids_are_accepted_but_not_scored(scored):
    """Mensagens antigas do navegador têm ids como `assistant-1700000000000`: nada a vincular."""
    resp = client.post("/api/feedback", json={"message_id": "assistant-1700000000000", "rating": "positive"})
    assert resp.status_code == 202 and resp.json()["registrado"] is False
    scored.assert_not_called()


def test_feedback_never_fails_when_langfuse_is_down():
    with patch("src.observability.tracing.score_trace_by_id", side_effect=RuntimeError("fora do ar")):
        resp = client.post("/api/feedback", json={"message_id": TRACE_ID, "rating": "positive"})
    assert resp.status_code == 202 and resp.json()["registrado"] is False


def test_feedback_with_tracing_off_is_accepted_and_reports_not_registered():
    with patch("src.observability.tracing.score_trace_by_id", return_value=False):
        resp = client.post("/api/feedback", json={"message_id": TRACE_ID, "rating": "negative"})
    assert resp.status_code == 202 and resp.json()["registrado"] is False


def test_trace_id_format_used_by_the_adapter_matches_the_feedback_check():
    assert re.fullmatch(r"[0-9a-f]{32}", TRACE_ID)


# ------------------------------------ keepalive do SSE ------------------------------------ #

def test_long_checks_send_keepalive_comments_so_proxies_do_not_cut_the_stream(fake_check):
    """O Ollama local leva dezenas de segundos: sem tráfego, nginx e navegadores encerram a conexão."""
    import time
    from src.services import frontend_api

    original = router_service._run_check.side_effect

    def slow(claim_text, start_total, on_step=None):
        time.sleep(0.12)
        return original(claim_text, start_total, on_step)

    with patch.object(frontend_api, "HEARTBEAT_SECONDS", 0.02), \
         patch.object(router_service, "_run_check", side_effect=slow):
        text = client.post("/api/check/stream", json={"query": CLAIM}).text
    assert ": keepalive" in text
    assert "event: done" in text
