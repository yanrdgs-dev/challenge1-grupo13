"""Guarda de especificidade para claims eleitorais (Fase 1, passo 5; regra 3 da AGENTS.md).

Claim sobre resultado de eleição sem ano, com turno sem ano, com "a última eleição" ou sobre evento futuro
é INCONCLUSIVO antes de qualquer LLM ou tool de dado. Claims com o ano, e claims de regra ou de acesso a
dados, passam.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.guardrails.actions import check_input_specificity
from src.services import router_service

BLOCKED = [
    "O Lula ganhou no primeiro turno.",
    "Bolsonaro perdeu no segundo turno com mais de 58 milhões de votos.",
    "Na última eleição, o candidato do PT venceu para presidente.",
    "O vencedor da eleição passada para governador de São Paulo foi Tarcísio.",
    "O candidato foi eleito na eleição anterior com 60% dos votos.",
    "Quem ganhou a eleição presidencial foi Lula.",
    "O Tarcísio foi eleito governador de São Paulo.",
    "Haddad perdeu a eleição para governador.",
    "O 2º turno da eleição para presidente teve Lula como vencedor.",
    "Lula vai ganhar a eleição de 2026.",
    "Flávio Bolsonaro será eleito presidente em 2026.",
    "O próximo presidente vai vencer a eleição no primeiro turno em 2030.",
]

ALLOWED = [
    "Lula venceu o segundo turno da eleição presidencial de 2022 com 60.345.999 votos.",
    "Em 2022, Bolsonaro teve 51 milhões de votos no primeiro turno.",
    "Tarcísio foi eleito governador de São Paulo em 2022.",
    "O TSE proíbe que se divulgue publicamente o teto de gastos de campanha para presidente e governador.",
    "Dá para ver no site do TSE quanto cada candidato declarou ter gastado na campanha eleitoral.",
    "Um partido pode receber a cota do Fundo Partidário sem prestar contas ao TSE.",
    "Nikolas Ferreira é deputado federal por Minas Gerais.",
    "O deputado Fulano de Tal votou a favor do PL 2630 de 2020.",
    "Em 2026, o candidato do PT venceu o primeiro turno.",
    "O turno único é regra para vereadores em qualquer eleição municipal?",
]


@pytest.mark.parametrize("claim", BLOCKED)
def test_underspecified_or_future_election_claims_are_inconclusive(claim):
    res = check_input_specificity(claim)
    assert res["is_valid"] is False, claim
    assert res["verdict"] == "INCONCLUSIVO"
    assert res["rule_matched"] == "guarda_de_especificidade"
    assert "Regra 3" in res["reason"]


@pytest.mark.parametrize("claim", ALLOWED)
def test_anchored_or_non_electoral_claims_pass(claim):
    # "Lula vai ganhar a eleição de 2026" é futuro e bloqueia mesmo com ano; as demais passam
    assert check_input_specificity(claim)["is_valid"] is True, claim


def test_reasons_do_not_depend_on_the_direction_of_the_claim():
    """Regra 6: a justificativa é a mesma para uma claim a favor e uma contra."""
    a = check_input_specificity("O candidato do PT ganhou no primeiro turno.")
    b = check_input_specificity("O candidato do PL ganhou no primeiro turno.")
    assert a["reason"] == b["reason"]


def test_no_golden_claim_that_was_valid_becomes_blocked():
    golden = json.loads((Path(__file__).resolve().parents[1] / "golden_dataset_v1.json").read_text())
    claims = golden if isinstance(golden, list) else golden.get("claims", golden)
    for item in claims:
        res = check_input_specificity(item["claim"])
        if item["expected_verdict"] != "INCONCLUSIVO":
            assert res["is_valid"] is True, item["claim"]


def test_router_answers_inconclusive_without_llm_or_tool_for_turn_without_year():
    client = TestClient(router_service.app)
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "execute_tool") as tool:
        resp = client.post("/check", json={"claim": "O Lula ganhou no primeiro turno."})
    data = resp.json()
    assert data["veredito"] == "INCONCLUSIVO" and data["regra_acionada"] == "guarda_de_especificidade"
    assert data["tool_usada"] is None
    llm.chat.assert_not_called()
    tool.assert_not_called()
