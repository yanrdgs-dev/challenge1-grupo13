"""Roteamento em duas etapas: resolver → tool de dados, com o ID sempre vindo do resolver (regra 2)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from scripts.demo_qwen_tool_routing import TOOLS_CATALOG
from src.core.llm_client import ChatResult
from src.services import router_service

client = TestClient(router_service.app)

CLAIM = "A urgência do PL 2630/2020 foi aprovada pelo Plenário da Câmara dos Deputados."
RESOLVED = {"id_proposicao": 2256735, "sigla_tipo": "PL", "numero": 2630, "ano": 2020, "casa": "camara",
            "ementa": "Institui a Lei Brasileira de Liberdade, Responsabilidade e Transparência na Internet.",
            "ambiguous": False, "candidatos": [], "match_score": 100.0}
AMBIGUOUS = {**RESOLVED, "id_proposicao": None, "ambiguous": True, "candidatos": [{"id": 1}, {"id": 2}]}
NOT_FOUND = {**RESOLVED, "id_proposicao": None, "ambiguous": False}
VOTES = [{"id_votacao": "v1", "data": "2023-04-25", "tipo_votacao": "Aprovado o Requerimento de Urgência", "aprovado": True}]
PLACAR = {"sim": 430, "nao": 12, "abstencao": 1, "obstrucao": 0, "ausente": 70, "total": 513}
JUDGE = {"veredito": "VERDADEIRO", "confianca": "ALTA", "justificativa": "Conforme a Câmara dos Deputados, aprovada.",
         "fontes_primarias": ["Câmara dos Deputados"], "tempo_julgamento_ms": 1.0}


def chat(*calls):
    return ChatResult(content="", tool_calls=list(calls), provider="ollama", model="qwen2.5:7b")


RESOLVE_CALL = {"name": "resolve_proposition", "arguments": {"casa": "camara", "sigla_tipo": "PL", "numero": 2630, "ano": 2020}}
VOTE_CALL_INVENTED = {"name": "get_proposition_vote_result", "arguments": {"casa": "camara", "id_proposicao": 12345}}


@pytest.fixture
def tools():
    with patch.object(router_service, "resolve_proposition", return_value=RESOLVED) as resolver, \
         patch.object(router_service, "get_proposition_vote_result", return_value=VOTES) as votes, \
         patch.object(router_service, "get_proposition_vote_breakdown", return_value=PLACAR) as breakdown, \
         patch.object(router_service, "_call_judge", return_value=JUDGE) as judge, \
         patch.object(router_service, "llm_client") as llm:
        llm.chat.return_value = chat(RESOLVE_CALL)
        yield SimpleTools(resolver, votes, judge, llm, breakdown)


class SimpleTools:
    def __init__(self, resolver, votes, judge, llm, breakdown=None):
        self.resolver, self.votes, self.judge, self.llm, self.breakdown = resolver, votes, judge, llm, breakdown


def post():
    return client.post("/check", json={"claim": CLAIM}).json()


# ------------------------------ encadeamento normal ------------------------------ #

def test_resolved_proposition_chains_to_the_vote_tool_with_the_resolved_id(tools):
    data = post()
    tools.votes.assert_called_once_with(id_proposicao="2256735", casa="camara")
    assert data["tool_usada"] == "get_proposition_vote_result"
    assert data["ferramentas_usadas"] == [
        "resolve_proposition", "get_proposition_vote_result", "get_proposition_vote_breakdown"]
    assert data["evidencia_coletada"]["votacoes"] == [{**VOTES[0], "placar": PLACAR}]
    assert data["evidencia_coletada"]["entidade_resolvida"]["id_proposicao"] == 2256735
    assert data["evidencia_coletada"]["entidade_resolvida"]["ementa"].startswith("Institui")


def test_chaining_costs_a_single_llm_call(tools):
    post()
    assert tools.llm.chat.call_count == 1


def test_chained_verdict_cites_the_house_source(tools):
    data = post()
    assert data["veredito"] == "VERDADEIRO"
    assert "Câmara dos Deputados - Dados Abertos" in data["fontes_primarias"]


def test_both_steps_are_sibling_tool_spans(trace_recorder, tools):
    post()
    assert [(n, p) for n, p in trace_recorder.tree() if n.startswith("tool.")] == [
        ("tool.resolve_proposition", "check_claim"),
        ("tool.get_proposition_vote_result", "check_claim"),
        ("tool.get_proposition_vote_breakdown", "check_claim"),
    ]


def test_root_metadata_records_the_tool_chain(trace_recorder, tools):
    post()
    assert trace_recorder.merged_updates("check_claim")["metadata"]["ferramentas_usadas"] == [
        "resolve_proposition", "get_proposition_vote_result", "get_proposition_vote_breakdown"]


# --------------------------- resolução que não sustenta dado --------------------------- #

@pytest.mark.parametrize("resolution", [AMBIGUOUS, NOT_FOUND])
def test_unresolved_or_ambiguous_proposition_never_reaches_the_vote_tool(tools, resolution):
    tools.resolver.return_value = resolution
    data = post()
    tools.votes.assert_not_called()
    assert data["tool_usada"] == "resolve_proposition"
    assert data["ferramentas_usadas"] == ["resolve_proposition"]


@pytest.mark.parametrize("resolution", [AMBIGUOUS, NOT_FOUND])
def test_unresolved_proposition_cannot_support_a_verdict(tools, resolution):
    tools.resolver.return_value = resolution
    tools.judge.return_value = {**JUDGE, "veredito": "FALSO"}
    assert post()["veredito"] == "INCONCLUSIVO"


def test_congress_proposition_is_not_chained_to_a_single_house_vote_tool(tools):
    tools.resolver.return_value = {**RESOLVED, "casa": "congresso"}
    post()
    tools.votes.assert_not_called()


def test_vote_tool_failure_keeps_the_resolution_and_degrades_to_inconclusive(tools):
    tools.votes.side_effect = RuntimeError("API da Câmara fora do ar")
    tools.judge.return_value = {**JUDGE, "veredito": "FALSO"}
    data = post()
    assert data["veredito"] == "INCONCLUSIVO"
    assert "API da Câmara fora do ar" in data["evidencia_coletada"]["erro"]
    assert data["evidencia_coletada"]["entidade_resolvida"]["id_proposicao"] == 2256735


# ------------------------------ guarda da regra 2 ------------------------------ #

def test_invented_vote_id_is_discarded_and_replaced_by_the_resolved_one(tools):
    tools.llm.chat.side_effect = [chat(VOTE_CALL_INVENTED), chat(RESOLVE_CALL)]
    data = post()
    tools.votes.assert_called_once_with(id_proposicao="2256735", casa="camara")   # nunca 12345
    assert data["ferramentas_usadas"][:2] == ["resolve_proposition", "get_proposition_vote_result"]


def test_guard_reroutes_with_a_catalog_restricted_to_the_resolver(tools):
    tools.llm.chat.side_effect = [chat(VOTE_CALL_INVENTED), chat(RESOLVE_CALL)]
    post()
    first, second = tools.llm.chat.call_args_list
    assert first.kwargs["tools"] == TOOLS_CATALOG
    assert [t["function"]["name"] for t in second.kwargs["tools"]] == ["resolve_proposition"]


def test_guard_without_a_resolution_never_calls_the_vote_tool(tools):
    tools.llm.chat.side_effect = [chat(VOTE_CALL_INVENTED), chat()]     # o LLM não resolveu
    tools.judge.return_value = {**JUDGE, "veredito": "FALSO"}
    data = post()
    tools.votes.assert_not_called()
    assert data["veredito"] == "INCONCLUSIVO"
    assert data["evidencia_coletada"]["status"] == "entidade_nao_resolvida"


def test_guard_llm_failure_is_a_503(tools):
    tools.llm.chat.side_effect = [chat(VOTE_CALL_INVENTED), RuntimeError("Ollama caiu")]
    assert client.post("/check", json={"claim": CLAIM}).status_code == 503


# ------------------------------ o resto não muda ------------------------------ #

def test_single_step_tools_report_a_one_tool_chain(tools):
    tools.llm.chat.return_value = chat({"name": "get_top_ceap_spender", "arguments": {"casa": "camara", "ano": 2023}})
    with patch.object(router_service, "get_top_ceap_spender") as spender:
        spender.return_value.to_dict.return_value = {"gastadores": []}
        data = post()
    assert data["ferramentas_usadas"] == ["get_top_ceap_spender"]
    tools.votes.assert_not_called()


def test_no_tool_means_empty_chain(tools):
    tools.llm.chat.return_value = chat()
    assert post()["ferramentas_usadas"] == []


def test_claim_blocked_by_input_rail_has_empty_chain():
    resp = client.post("/check", json={"claim": "Um deputado gastou muito dinheiro público recentemente."})
    assert resp.json()["ferramentas_usadas"] == []


# ------------------- tarefa 3.9: placar das votações na etapa 2 ------------------- #

def _vote(id_votacao, data):
    return {"id_votacao": id_votacao, "data": data, "tipo_votacao": "Votação", "aprovado": True}


def test_breakdown_uses_the_vote_id_from_the_vote_tool_never_from_the_llm(tools):
    tools.votes.return_value = [_vote("2256735-77", "2023-05-30")]
    post()
    tools.breakdown.assert_called_once_with(id_votacao="2256735-77", casa="camara")


def test_breakdown_only_for_the_three_most_recent_votes(tools):
    tools.votes.return_value = [
        _vote("a", "2021-01-01"), _vote("b", "2023-03-01"), _vote("c", "2022-02-01"),
        _vote("d", "2024-04-01"), _vote("e", "2020-05-01"),
    ]
    data = post()
    assert [c.kwargs["id_votacao"] for c in tools.breakdown.call_args_list] == ["d", "b", "c"]
    by_id = {v["id_votacao"]: v for v in data["evidencia_coletada"]["votacoes"]}
    assert by_id["d"]["placar"] == PLACAR
    assert "placar" not in by_id["a"] and "placar" not in by_id["e"]


def test_no_votes_means_no_breakdown_call(tools):
    tools.votes.return_value = []
    data = post()
    tools.breakdown.assert_not_called()
    assert data["ferramentas_usadas"] == ["resolve_proposition", "get_proposition_vote_result"]


def test_breakdown_failure_keeps_the_vote_list_and_flags_the_missing_tally(tools):
    tools.breakdown.side_effect = RuntimeError("API fora do ar")
    data = post()
    vote = data["evidencia_coletada"]["votacoes"][0]
    assert vote["id_votacao"] == "v1" and vote["aprovado"] is True
    assert vote["placar"] is None
    assert "API fora do ar" in vote["placar_erro"]
    assert data["veredito"] == "VERDADEIRO"            # a lista de votações segue sustentando o veredito


def test_zeroed_breakdown_is_not_reported_as_a_tally(tools):
    tools.breakdown.return_value = {"sim": 0, "nao": 0, "abstencao": 0, "obstrucao": 0, "ausente": 0, "total": 0}
    vote = post()["evidencia_coletada"]["votacoes"][0]
    assert vote["placar"] is None
    assert "placar_erro" in vote


def test_vote_tool_failure_skips_the_breakdown(tools):
    tools.votes.side_effect = RuntimeError("API da Câmara fora do ar")
    post()
    tools.breakdown.assert_not_called()
