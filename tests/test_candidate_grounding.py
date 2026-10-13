"""Ancoragem dos filtros de candidato na claim (Fase 1, passo 6; regras 2 e 3 da AGENTS.md).

O LLM de roteamento pode preencher `cargo`, `uf` ou `numero` por conta própria. Em 2022 havia dois "Pablo Marçal"
(Presidente, cancelado; Deputado Federal por SP) e, com o cargo errado, a tool resolvia a outra candidatura e o
juiz dava FALSO. Filtro que não está escrito na claim é descartado: o homônimo volta a ser ambíguo (INCONCLUSIVO).
"""

from unittest.mock import MagicMock, patch

import pytest

from src.services import router_service
from src.services.tool_args import ground_candidate_args

CLAIM = "O registro de candidatura de Pablo Marçal à Presidência da República em 2022 consta como cancelado no TSE."


@pytest.mark.parametrize("cargo,claim,kept", [
    ("Presidente", "O registro de candidatura de Pablo Marçal à Presidência da República em 2022 foi cancelado.", True),
    ("Presidente", "Lula venceu a eleição presidencial de 2022.", True),
    ("Governador", "Tarcísio foi eleito governador de São Paulo em 2022.", True),
    ("Senador", "Fulano foi eleito senador por Goiás em 2022.", True),
    ("Deputado Federal", "José Silva foi eleito deputado federal em 2022.", True),
    ("Deputado Estadual", "Fulano foi eleito Deputado Estadual em 2022.", True),
    ("Deputado Distrital", "Fulano foi eleito deputada distrital em 2022.", True),
    ("Deputado Federal", CLAIM, False),
    ("Presidente", "Pablo Marçal teve a candidatura cancelada em 2022.", False),
    ("Deputado Federal", "José Silva foi eleito deputado em 2022.", False),  # "deputado" sozinho não diz qual
    ("Senador", "O deputado federal Fulano foi eleito em 2022.", False),
])
def test_cargo_is_kept_only_when_the_claim_says_it(cargo, claim, kept):
    args = ground_candidate_args("check_candidate_status", {"nome_candidato": "X", "ano": 2022, "cargo": cargo}, claim)
    assert ("cargo" in args) is kept


@pytest.mark.parametrize("uf,claim,kept", [
    ("SP", "José Silva foi eleito deputado federal por São Paulo em 2022.", True),
    ("SP", "José Silva (PL-SP) foi eleito deputado federal em 2022.", True),
    ("MG", "Fulano foi eleito em Minas Gerais em 2022.", True),
    ("DF", "Fulano foi eleito deputado distrital no Distrito Federal em 2022.", True),
    ("SP", CLAIM, False),
    ("RS", "Pablo Marçal teve a candidatura cancelada em 2022 no Brasil.", False),
    ("PA", "Fulano foi eleito para o Senado em 2022.", False),  # a preposição "para" não é o estado do Pará
    ("PA", "Fulano foi eleito senador pelo Pará em 2022.", True),
    ("MT", "Fulano foi eleito em Mato Grosso do Sul em 2022.", False),  # MS, não MT
    ("MS", "Fulano foi eleito em Mato Grosso do Sul em 2022.", True),
])
def test_uf_is_kept_only_when_the_claim_says_it(uf, claim, kept):
    args = ground_candidate_args("get_candidate_assets", {"nome_candidato": "X", "ano": 2022, "uf": uf}, claim)
    assert ("uf" in args) is kept


def test_numero_is_kept_only_when_it_appears_in_the_claim():
    ok = ground_candidate_args("resolve_candidate", {"nome_busca": "X", "ano": 2022, "numero": 13}, "O candidato 13 teve 60 milhões em 2022.")
    gone = ground_candidate_args("resolve_candidate", {"nome_busca": "X", "ano": 2022, "numero": 13}, "Lula teve 60 milhões em 2022.")
    assert ok["numero"] == 13 and "numero" not in gone


def test_other_arguments_are_untouched_and_the_input_is_not_mutated():
    original = {"nome_candidato": "Pablo", "ano": 2022, "turno": 1, "cargo": "Deputado Federal", "termo": "@x"}
    snapshot = dict(original)
    args = ground_candidate_args("verify_official_social_media", original, CLAIM)
    assert original == snapshot
    assert args == {"nome_candidato": "Pablo", "ano": 2022, "turno": 1, "termo": "@x"}


@pytest.mark.parametrize("tool", ["get_election_result", "get_top_campaign_finances", "check_institutional_rule",
                                  "resolve_politician", "ferramenta_inexistente"])
def test_tools_that_do_not_resolve_a_candidate_are_not_touched(tool):
    args = {"cargo": "Presidente", "ano": 2022, "uf": "SP"}
    assert ground_candidate_args(tool, args, "qualquer coisa") == args


def test_non_dict_args_pass_through():
    assert ground_candidate_args("check_candidate_status", None, CLAIM) is None


# ---------------------------------------------------------------- no roteador

def test_router_drops_the_ungrounded_cargo_before_resolving_the_candidate():
    chat = MagicMock()
    chat.tool_calls = [{"name": "check_candidate_status",
                        "arguments": {"nome_candidato": "Pablo Marçal", "ano": 2022, "cargo": "Deputado Federal", "uf": "SP"}}]
    with patch.object(router_service, "_chat_for_routing", return_value=chat), \
         patch.object(router_service, "resolve_candidate",
                      return_value={"encontrado": False, "status": "ambiguo", "sq_candidato": None, "ambiguous": True,
                                    "candidatos_alternativos": [{"sq_candidato": 1}, {"sq_candidato": 2}]}) as resolver, \
         patch.object(router_service, "check_candidate_status") as status_tool:
        outcome = router_service._route_and_execute(CLAIM)
    kwargs = resolver.call_args.kwargs
    assert kwargs["cargo"] is None and kwargs["uf"] is None
    status_tool.assert_not_called()
    assert outcome.evidence["status"] == "entidade_nao_resolvida" and outcome.evidence["ambiguous"] is True
    assert "cargo" not in outcome.tool_args and "uf" not in outcome.tool_args


def test_router_keeps_a_cargo_that_the_claim_states():
    chat = MagicMock()
    chat.tool_calls = [{"name": "check_candidate_status",
                        "arguments": {"nome_candidato": "Pablo Marçal", "ano": 2022, "cargo": "Presidente"}}]
    resolved = {"encontrado": True, "sq_candidato": 7, "ambiguous": False, "nome_urna": "PABLO MARÇAL"}
    with patch.object(router_service, "_chat_for_routing", return_value=chat), \
         patch.object(router_service, "resolve_candidate", return_value=resolved) as resolver, \
         patch.object(router_service, "check_candidate_status", return_value={"encontrado": True}):
        router_service._route_and_execute(CLAIM)
    assert resolver.call_args.kwargs["cargo"] == "Presidente"
