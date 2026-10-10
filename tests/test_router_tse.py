"""Integração das tools de resultado do TSE no roteador: catálogo, despacho, fonte e data da base (Fase 1, passo 2)."""

from unittest.mock import patch

import pytest

from src.services import router_service
from src.services.data_freshness import data_date
from src.services.router_service import execute_tool
from src.services.sources import TSE, derive_sources, evidence_failed
from src.services.tool_args import validate_tool_args
from src.services.tool_catalog import ROUTER_SYSTEM_PROMPT, TOOLS_CATALOG

RESOLVED = {"encontrado": True, "status": "resolvido", "sq_candidato": 77, "nome_urna": "LULA", "nome_civil": "LUIZ",
            "cargo": "PRESIDENTE", "uf": "BR", "partido": "PT", "ano": 2022, "turnos": [1, 2],
            "ambiguous": False, "candidatos_alternativos": []}
AMBIGUOUS = {"encontrado": False, "status": "ambiguo", "sq_candidato": None, "ambiguous": True,
             "candidatos_alternativos": [{"sq_candidato": 1}, {"sq_candidato": 2}]}
NOT_FOUND = {"encontrado": False, "status": "nao_encontrado", "sq_candidato": None, "ambiguous": False,
             "candidatos_alternativos": []}
VOTES = {"encontrado": True, "status": "ok", "sq_candidato": 77, "votos_validos": 10, "ano": 2022, "turno": 1}


@pytest.fixture(autouse=True)
def _votes_published():
    """Por padrão a votação do ano existe; os testes de 2026 sobrescrevem."""
    with patch.object(router_service, "election_results_available", return_value=True):
        yield


def _tool(name):
    return next(t["function"] for t in TOOLS_CATALOG if t["function"]["name"] == name)


# ------------------------------ catálogo ------------------------------ #

def test_catalog_exposes_the_three_tse_tools_with_ano_and_turno_required():
    assert "ano" in _tool("resolve_candidate")["parameters"]["required"]
    assert {"cargo", "ano", "turno"} <= set(_tool("get_election_result")["parameters"]["required"])
    assert {"nome_candidato", "ano", "turno"} <= set(_tool("get_candidate_votes")["parameters"]["required"])


def test_missing_turno_is_rejected_before_any_tool_runs():
    _, problem = validate_tool_args("get_election_result", {"cargo": "Presidente", "ano": 2022})
    assert problem and "turno" in problem
    result = execute_tool("get_election_result", {"cargo": "Presidente", "ano": 2022})
    assert result["status"] == "parametros_invalidos" and evidence_failed(result)


def test_prompt_tells_the_router_to_use_tse_tools_and_not_to_guess_year_or_turn():
    text = ROUTER_SYSTEM_PROMPT
    assert "get_election_result" in text and "get_candidate_votes" in text
    assert "NÃO invente" in text or "nunca invente" in text.lower()


# ------------------------------ despacho ------------------------------ #

def test_get_election_result_is_dispatched_with_normalized_args():
    with patch.object(router_service, "get_election_result", return_value={"encontrado": True}) as tool:
        execute_tool("get_election_result", {"cargo": "presidente", "ano": "2022", "turno": 2})
    tool.assert_called_once_with(cargo="Presidente", ano=2022, turno=2, uf=None)


def test_resolve_candidate_is_dispatched():
    with patch.object(router_service, "resolve_candidate", return_value=RESOLVED) as tool:
        res = execute_tool("resolve_candidate", {"nome_busca": "Lula", "ano": 2022, "cargo": "Presidente"})
    assert res["sq_candidato"] == 77
    assert tool.call_args.kwargs["ano"] == 2022


def test_candidate_votes_resolves_the_name_first_and_uses_the_canonical_id():
    with patch.object(router_service, "resolve_candidate", return_value=RESOLVED) as resolver, \
         patch.object(router_service, "get_candidate_votes", return_value=dict(VOTES)) as votes:
        res = execute_tool("get_candidate_votes", {"nome_candidato": "Lula", "ano": 2022, "turno": 1})
    resolver.assert_called_once()
    votes.assert_called_once_with(sq_candidato=77, ano=2022, turno=1)
    assert res["votos_validos"] == 10
    assert res["entidade_resolvida"]["sq_candidato"] == 77


def test_candidate_votes_with_ambiguous_name_never_reaches_the_data_tool():
    with patch.object(router_service, "resolve_candidate", return_value=AMBIGUOUS), \
         patch.object(router_service, "get_candidate_votes") as votes:
        res = execute_tool("get_candidate_votes", {"nome_candidato": "João Silva", "ano": 2022, "turno": 1})
    votes.assert_not_called()
    assert res["status"] == "entidade_nao_resolvida" and res["ambiguous"] is True and evidence_failed(res)


def test_candidate_votes_with_unknown_name_never_reaches_the_data_tool():
    with patch.object(router_service, "resolve_candidate", return_value=NOT_FOUND), \
         patch.object(router_service, "get_candidate_votes") as votes:
        res = execute_tool("get_candidate_votes", {"nome_candidato": "Ninguém", "ano": 2022, "turno": 1})
    votes.assert_not_called()
    assert res["status"] == "entidade_nao_resolvida" and evidence_failed(res)


# ------------------------- fonte e data da base ------------------------- #

def test_tse_tools_cite_the_tse_as_source():
    for tool in ("resolve_candidate", "get_election_result", "get_candidate_votes"):
        assert derive_sources(tool, {}, {"encontrado": True, "status": "ok"}) == [TSE], tool


def test_empty_tse_evidence_has_no_source_and_counts_as_failed():
    empty = {"encontrado": False, "status": "resultado_indisponivel"}
    assert evidence_failed(empty)
    assert derive_sources("get_election_result", {}, empty) == []


INFO = {"fontes": {
    "tse-consulta_cand_2022": {"baixado_em": "2026-10-10T10:00:00+00:00"},
    "tse-consulta_cand_2026": {"baixado_em": "2026-10-10T11:00:00+00:00"},
    "tse-votacao_candidato_munzona_2022": {"baixado_em": "2026-10-09T09:00:00+00:00"},
}}


def test_data_date_of_tse_tools_follows_the_year_of_the_table_read():
    ok = {"encontrado": True}
    assert data_date("get_election_result", {"ano": 2022}, ok, INFO) == "2026-10-09T09:00:00+00:00"
    assert data_date("get_candidate_votes", {"ano": 2022}, ok, INFO) == "2026-10-09T09:00:00+00:00"
    assert data_date("resolve_candidate", {"ano": 2026}, ok, INFO) == "2026-10-10T11:00:00+00:00"


# ------------------- 2026: dados abertos do TSE ainda não atualizados ------------------- #

from fastapi.testclient import TestClient  # noqa: E402

from src.core.llm_client import ChatResult  # noqa: E402

UNAVAILABLE_2026 = {
    "encontrado": False, "status": "resultado_indisponivel", "ano": 2026, "candidatos": [],
    "motivo": "Os dados abertos do TSE ainda não foram atualizados com o resultado da eleição de 2026.",
}


def test_candidate_votes_for_2026_does_not_even_resolve_the_name():
    with patch.object(router_service, "election_results_available", return_value=False), \
         patch.object(router_service, "resolve_candidate") as resolver, \
         patch.object(router_service, "get_candidate_votes") as votes:
        res = execute_tool("get_candidate_votes", {"nome_candidato": "Lula", "ano": 2026, "turno": 1})
    resolver.assert_not_called()
    votes.assert_not_called()
    assert res["status"] == "resultado_indisponivel" and res["ano"] == 2026
    assert "ainda não foram atualizados" in res["motivo"]


def test_claim_about_2026_result_answers_that_open_data_is_not_updated_without_calling_the_judge():
    client = TestClient(router_service.app)
    chat = ChatResult(content="", provider="ollama", model="m", usage={},
                      tool_calls=[{"name": "get_election_result",
                                   "arguments": {"cargo": "Presidente", "ano": 2026, "turno": 1}}])
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "execute_tool", return_value=UNAVAILABLE_2026), \
         patch.object(router_service, "_call_judge") as judge:
        llm.chat.return_value = chat
        resp = client.post("/check", json={"claim": "O candidato do PT venceu o primeiro turno da eleição presidencial de 2026."})
    judge.assert_not_called()
    body = resp.json()
    assert body["veredito"] == "INCONCLUSIVO"
    assert "ainda não foram atualizados" in body["justificativa"]
    assert body["regra_acionada"] == "dados_tse_nao_atualizados"
    assert body["tool_usada"] == "get_election_result"


# ------------------- situação da candidatura e motivos de indeferimento ------------------- #

STATUS = {"encontrado": True, "status": "ok", "sq_candidato": 77, "detalhe_situacao": "DEFERIDO"}


def test_catalog_has_status_and_motive_tools_with_ano_required_and_no_turno():
    for name in ("check_candidate_status", "check_disqualification_motive"):
        params = _tool(name)["parameters"]
        assert {"nome_candidato", "ano"} <= set(params["required"]), name
        assert "turno" not in params["required"], name


def test_status_tool_resolves_the_name_first_and_uses_the_canonical_id():
    with patch.object(router_service, "resolve_candidate", return_value=RESOLVED) as resolver, \
         patch.object(router_service, "check_candidate_status", return_value=dict(STATUS)) as tool:
        res = execute_tool("check_candidate_status", {"nome_candidato": "Lula", "ano": 2022})
    resolver.assert_called_once()
    tool.assert_called_once_with(sq_candidato=77, ano=2022)
    assert res["detalhe_situacao"] == "DEFERIDO" and res["entidade_resolvida"]["sq_candidato"] == 77


def test_motive_tool_resolves_the_name_first_and_uses_the_canonical_id():
    with patch.object(router_service, "resolve_candidate", return_value=RESOLVED), \
         patch.object(router_service, "check_disqualification_motive", return_value={"encontrado": True, "motivos": []}) as tool:
        res = execute_tool("check_disqualification_motive", {"nome_candidato": "Lula", "ano": 2022})
    tool.assert_called_once_with(sq_candidato=77, ano=2022)
    assert res["entidade_resolvida"]["sq_candidato"] == 77


@pytest.mark.parametrize("name", ["check_candidate_status", "check_disqualification_motive"])
@pytest.mark.parametrize("resolution", [AMBIGUOUS, NOT_FOUND])
def test_status_and_motive_never_reach_the_data_tool_with_unresolved_name(name, resolution):
    with patch.object(router_service, "resolve_candidate", return_value=resolution), \
         patch.object(router_service, name) as tool:
        res = execute_tool(name, {"nome_candidato": "João Silva", "ano": 2022})
    tool.assert_not_called()
    assert res["status"] == "entidade_nao_resolvida" and evidence_failed(res)


def test_status_for_2026_still_resolves_because_candidacies_are_published():
    with patch.object(router_service, "election_results_available", return_value=False), \
         patch.object(router_service, "resolve_candidate", return_value=RESOLVED), \
         patch.object(router_service, "check_candidate_status", return_value=dict(STATUS)):
        res = execute_tool("check_candidate_status", {"nome_candidato": "Lula", "ano": 2026})
    assert res["encontrado"] is True


def test_sources_and_base_date_of_status_and_motive_tools():
    for tool in ("check_candidate_status", "check_disqualification_motive"):
        assert derive_sources(tool, {}, {"encontrado": True, "status": "ok"}) == [TSE]
    info = {"fontes": {
        "tse-consulta_cand_complementar_2022": {"baixado_em": "2026-10-10T12:00:00+00:00"},
        "tse-motivo_cassacao_2022": {"baixado_em": "2026-10-10T13:00:00+00:00"},
    }}
    ok = {"encontrado": True}
    assert data_date("check_candidate_status", {"ano": 2022}, ok, info) == "2026-10-10T12:00:00+00:00"
    assert data_date("check_disqualification_motive", {"ano": 2022}, ok, info) == "2026-10-10T13:00:00+00:00"


def test_motive_result_warns_that_absence_of_a_row_is_not_proof_of_regularity(tmp_path):
    from src.tools.tse_tools import check_disqualification_motive
    import polars as pl
    for table, rows in {
        "candidatos": [{"SQ_CANDIDATO": 4, "NM_CANDIDATO": "X", "NM_URNA_CANDIDATO": "X", "SG_PARTIDO": "PT",
                        "DS_CARGO": "PRESIDENTE", "SG_UF": "BR", "NR_TURNO": 1, "DS_SIT_TOT_TURNO": "#NE",
                        "DS_SITUACAO_CANDIDATURA": "INAPTO"}],
        "cassacao": [{"SQ_CANDIDATO": 9, "DS_TP_MOTIVO": "t", "DS_MOTIVO": "m", "NR_PROCESSO": 1}],
    }.items():
        folder = tmp_path / "tse" / table / "ano=2022"
        folder.mkdir(parents=True)
        pl.DataFrame(rows).write_parquet(folder / "p.parquet")
    res = check_disqualification_motive(4, ano=2022, base_dir=tmp_path)
    assert res["total_motivos"] == 0 and "não prova" in res["aviso"]
