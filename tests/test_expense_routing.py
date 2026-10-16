"""Pergunta de gasto de parlamentar nomeado: a tool sai da redação, não da sorte do modelo da rodada.

Em produção o rodízio (Ollama, Groq, DeepSeek) escolhia só `resolve_politician` para "Quanto o deputado Nikolas
Ferreira gastou em 2023?" em 2 de 3 vezes, e o juiz recebia só a identificação do deputado.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.services import router_service

CLAIM = "Quanto o deputado Nikolas Ferreira gastou da cota parlamentar em 2023?"
EXPENSES_ARGS = {"casa": "camara", "ano": 2023, "parlamentar": "Nikolas Ferreira"}


def _chat(name, arguments):
    chat = MagicMock()
    chat.tool_calls = [{"name": name, "arguments": arguments}]
    return chat


def _route(first_call, retry_call=None, claim=CLAIM):
    side_effect = [_chat(*first_call)] + ([_chat(*retry_call)] if retry_call else [])
    with patch.object(router_service, "category_for", return_value="GASTOS"), \
         patch.object(router_service, "_chat_for_routing", side_effect=side_effect) as chat_for_routing, \
         patch.object(router_service, "execute_tool", return_value={"qtd_lancamentos": 236, "valor_total": 218898.2}) as execute:
        outcome = router_service._route_and_execute(claim)
    return outcome, chat_for_routing, execute


def test_resolver_chosen_for_an_expense_question_is_redone_with_the_expenses_tool_alone():
    outcome, chat_for_routing, execute = _route(
        ("resolve_politician", {"nome_busca": "Nikolas Ferreira"}), ("get_member_expenses", EXPENSES_ARGS)
    )
    assert chat_for_routing.call_count == 2
    retry_catalog = chat_for_routing.call_args_list[1].args[1]
    assert [t["function"]["name"] for t in retry_catalog] == ["get_member_expenses"]
    assert outcome.tool_name == "get_member_expenses"
    execute.assert_called_once()
    assert execute.call_args.args[0] == "get_member_expenses"
    assert outcome.evidence["valor_total"] == 218898.2


def test_the_right_choice_is_not_redone():
    outcome, chat_for_routing, _ = _route(("get_member_expenses", EXPENSES_ARGS))
    assert chat_for_routing.call_count == 1 and outcome.tool_name == "get_member_expenses"


def test_if_the_retry_fails_the_original_choice_stands():
    from fastapi import HTTPException
    with patch.object(router_service, "category_for", return_value="GASTOS"), \
         patch.object(router_service, "_chat_for_routing",
                      side_effect=[_chat("resolve_politician", {"nome_busca": "Nikolas Ferreira"}), HTTPException(503, "fora")]), \
         patch.object(router_service, "execute_tool", return_value={"ambiguous": False}):
        outcome = router_service._route_and_execute(CLAIM)
    assert outcome.tool_name == "resolve_politician"


@pytest.mark.parametrize("claim", [
    "O deputado Nikolas Ferreira é do PL?",
    "O deputado Nikolas Ferreira gastou R$ 1 milhão na campanha de 2022.",
])
def test_other_questions_about_the_same_member_keep_the_resolver(claim):
    outcome, chat_for_routing, _ = _route(("resolve_politician", {"nome_busca": "Nikolas Ferreira"}), claim=claim)
    assert chat_for_routing.call_count == 1 and outcome.tool_name == "resolve_politician"
