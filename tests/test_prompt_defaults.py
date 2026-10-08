"""Prompts padrão (fallback local), uso no router/judge e publicação no Langfuse."""

import re
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from scripts.demo_qwen_tool_routing import ROUTER_SYSTEM_PROMPT
from src.core.llm_client import ChatResult
from src.observability.prompts import PromptResult
from src.prompts.defaults import (
    DEFAULT_PROMPTS,
    JUDGE_PROMPT_TEMPLATE,
    PROMPT_JUDGE,
    PROMPT_ROUTER_SYSTEM,
)
from src.services import judge_service, router_service


# --------------------------------- padrões --------------------------------- #

def test_default_prompt_names_and_registry():
    assert PROMPT_ROUTER_SYSTEM == "factcheck-router-system"
    assert PROMPT_JUDGE == "factcheck-judge"
    assert set(DEFAULT_PROMPTS) == {PROMPT_ROUTER_SYSTEM, PROMPT_JUDGE}


def test_router_default_is_the_current_system_prompt():
    assert DEFAULT_PROMPTS[PROMPT_ROUTER_SYSTEM] == ROUTER_SYSTEM_PROMPT


def test_judge_template_uses_only_the_three_langfuse_variables():
    assert set(re.findall(r"\{\{\s*(\w+)\s*\}\}", JUDGE_PROMPT_TEMPLATE)) == {"claim", "tool_used", "evidence"}


def test_judge_template_keeps_the_rules_and_the_json_contract():
    for expected in ("VERDADEIRO", "FALSO", "INCONCLUSIVO", "veredito", "confianca", "justificativa",
                     "fontes_primarias", "ambiguous: true"):
        assert expected in JUDGE_PROMPT_TEMPLATE


# ------------------------------ uso no judge ------------------------------ #

def judge_result(content='{"veredito": "FALSO"}'):
    return ChatResult(content=content, provider="ollama", model="qwen2.5:14b")


def test_judge_builds_its_prompt_from_the_local_template_with_variables():
    with patch.object(judge_service, "llm_client") as llm:
        llm.chat.return_value = judge_result()
        TestClient(judge_service.app).post(
            "/judge", json={"claim": "Fulano é do PL", "evidence": {"partido": "PL"}, "tool_used": "resolve_politician"})
    content = llm.chat.call_args.args[0][0]["content"]
    assert 'ALEGAÇÃO:\n"Fulano é do PL"' in content
    assert "resolve_politician" in content and '"partido": "PL"' in content
    assert "{{" not in content                                # nenhuma variável sem substituir


def test_judge_without_evidence_says_so():
    with patch.object(judge_service, "llm_client") as llm:
        llm.chat.return_value = judge_result()
        TestClient(judge_service.app).post("/judge", json={"claim": "c"})
    assert "Nenhuma evidência primária localizada" in llm.chat.call_args.args[0][0]["content"]


def test_judge_uses_the_prompt_returned_by_langfuse():
    remote = PromptResult(text="PROMPT REMOTO v7", name=PROMPT_JUDGE, version=7, label="production", source="langfuse")
    with patch.object(judge_service, "llm_client") as llm, \
         patch.object(judge_service, "get_prompt", return_value=remote) as getter:
        llm.chat.return_value = judge_result()
        TestClient(judge_service.app).post("/judge", json={"claim": "c", "evidence": {"a": 1}, "tool_used": "t"})

    assert llm.chat.call_args.args[0][0]["content"] == "PROMPT REMOTO v7"
    args, kwargs = getter.call_args
    assert args[0] == PROMPT_JUDGE and args[1] == JUDGE_PROMPT_TEMPLATE
    assert kwargs["variables"]["claim"] == "c" and kwargs["variables"]["tool_used"] == "t"


def test_evidence_with_template_syntax_is_not_reinterpreted():
    """Dado externo com {{...}} não pode virar variável do prompt (injeção de template)."""
    with patch.object(judge_service, "llm_client") as llm:
        llm.chat.return_value = judge_result()
        TestClient(judge_service.app).post(
            "/judge", json={"claim": "c", "evidence": {"ementa": "{{claim}}"}, "tool_used": "t"})
    assert '"ementa": "{{claim}}"' in llm.chat.call_args.args[0][0]["content"]


# ------------------------------ uso no router ------------------------------ #

def test_router_uses_the_system_prompt_from_langfuse_plus_the_guard_hint():
    remote = PromptResult(text="SISTEMA REMOTO", name=PROMPT_ROUTER_SYSTEM, version=2, label="production",
                          source="langfuse")
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "get_prompt", return_value=remote) as getter:
        llm.chat.return_value = ChatResult(content="", tool_calls=[], provider="ollama", model="m")
        router_service._chat_for_routing("uma claim", [], hint=" +DICA")
    system = llm.chat.call_args.args[0][0]
    assert system == {"role": "system", "content": "SISTEMA REMOTO +DICA"}
    assert getter.call_args.args[:2] == (PROMPT_ROUTER_SYSTEM, ROUTER_SYSTEM_PROMPT)


def test_router_works_with_the_local_prompt_by_default():
    with patch.object(router_service, "llm_client") as llm:
        llm.chat.return_value = ChatResult(content="", tool_calls=[], provider="ollama", model="m")
        router_service._chat_for_routing("uma claim", [])
    assert llm.chat.call_args.args[0][0]["content"] == ROUTER_SYSTEM_PROMPT


# ------------------------- publicação no Langfuse (4.2) ------------------------- #

def test_push_creates_missing_prompts_with_the_production_label():
    from scripts.langfuse_push_prompts import push_prompts

    client = MagicMock()
    client.get_prompt.side_effect = Exception("404")
    result = push_prompts(client, DEFAULT_PROMPTS)

    assert client.create_prompt.call_count == 2
    for call in client.create_prompt.call_args_list:
        assert call.kwargs["labels"] == ["production"] and call.kwargs["type"] == "text"
    assert {r["action"] for r in result} == {"criado"}


def test_push_skips_prompts_that_did_not_change():
    from scripts.langfuse_push_prompts import push_prompts

    client = MagicMock()
    client.get_prompt.side_effect = lambda name, **kw: MagicMock(prompt=DEFAULT_PROMPTS[name], version=4)
    result = push_prompts(client, DEFAULT_PROMPTS)
    client.create_prompt.assert_not_called()
    assert {r["action"] for r in result} == {"sem mudança"}


def test_push_publishes_changed_prompts_as_staging_never_straight_to_production():
    from scripts.langfuse_push_prompts import push_prompts

    client = MagicMock()
    client.get_prompt.side_effect = lambda name, **kw: MagicMock(prompt="texto antigo", version=4)
    result = push_prompts(client, DEFAULT_PROMPTS)
    assert all(c.kwargs["labels"] == ["staging"] for c in client.create_prompt.call_args_list)
    assert {r["action"] for r in result} == {"nova versão (staging)"}


def test_push_reads_the_current_production_without_cache():
    from scripts.langfuse_push_prompts import push_prompts

    client = MagicMock()
    push_prompts(client, DEFAULT_PROMPTS)
    for call in client.get_prompt.call_args_list:
        assert call.kwargs["label"] == "production" and call.kwargs["cache_ttl_seconds"] == 0


def test_push_dry_run_does_not_write():
    from scripts.langfuse_push_prompts import push_prompts

    client = MagicMock()
    client.get_prompt.side_effect = Exception("404")
    push_prompts(client, DEFAULT_PROMPTS, dry_run=True)
    client.create_prompt.assert_not_called()


def test_push_cli_dry_run_and_exit_codes(capsys):
    from scripts.langfuse_push_prompts import main

    factory = MagicMock()
    assert main(["--dry-run"], client_factory=factory) == 0
    factory.assert_not_called()
    assert "factcheck-judge" in capsys.readouterr().out

    failing = MagicMock()
    failing.get_prompt.side_effect = Exception("404")
    failing.create_prompt.side_effect = Exception("401")
    assert main([], client_factory=lambda: failing) == 2
