"""Despacho do execute_tool do router para todas as tools do catálogo (com resolução de entidade)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from scripts.demo_qwen_tool_routing import TOOLS_CATALOG
from src.core.llm_client import ChatResult
from src.services import router_service
from src.services.router_service import execute_tool

RESOLVED_CAMARA = {
    "ideCadastro": 204379, "cod_senador": None, "sq_candidato": None,
    "nome_civil": "Fulano de Tal", "ambiguous": False, "candidatos_alternativos": [],
}
RESOLVED_SENADO = {
    "ideCadastro": None, "cod_senador": 5012, "sq_candidato": None,
    "nome_civil": "Beltrana", "ambiguous": False, "candidatos_alternativos": [],
}
NOT_FOUND = {"ideCadastro": None, "cod_senador": None, "sq_candidato": None, "ambiguous": False,
             "candidatos_alternativos": []}
AMBIGUOUS = {"ideCadastro": None, "cod_senador": None, "sq_candidato": None, "ambiguous": True,
             "candidatos_alternativos": [{"nome_civil": "A"}, {"nome_civil": "B"}]}


def _dataclass_like(payload):
    obj = MagicMock()
    obj.to_dict.return_value = payload
    return obj


# --------------------------- catálogo x despacho --------------------------- #

def test_every_catalog_tool_is_dispatched_and_none_is_simulated():
    """Nenhuma tool do catálogo pode cair no ramo 'não implementada'."""
    names = [t["function"]["name"] for t in TOOLS_CATALOG]
    with patch.object(router_service, "resolve_politician", return_value=RESOLVED_CAMARA), \
         patch.object(router_service, "resolve_proposition", return_value={"id": 1}), \
         patch.object(router_service, "get_top_ceap_spender", return_value=_dataclass_like({"ok": 1})), \
         patch.object(router_service, "list_expense_categories", return_value=_dataclass_like({"ok": 2})), \
         patch.object(router_service, "check_parliamentary_expenses", return_value=_dataclass_like({"ok": 3})), \
         patch.object(router_service, "get_proposition_vote_result", return_value=[]):
        args = {"casa": "camara", "ano": 2023, "nome_busca": "Fulano", "id_proposicao": 10}
        for name in names:
            result = execute_tool(name, args)
            assert "erro" not in result, name


def test_unknown_tool_returns_error_not_fake_evidence():
    result = execute_tool("tool_inexistente", {"a": 1})
    assert "erro" in result
    assert "tool_inexistente" in result["erro"]


# ------------------------------ get_top_ceap_spender ------------------------------ #

def test_get_top_ceap_spender_dispatch():
    with patch.object(router_service, "get_top_ceap_spender",
                      return_value=_dataclass_like({"gastadores": [{"posicao": 1}]})) as tool:
        result = execute_tool("get_top_ceap_spender", {"casa": "camara", "ano": 2023, "top_n": 3})

    tool.assert_called_once_with(casa="camara", ano=2023, top_n=3)
    assert result == {"gastadores": [{"posicao": 1}]}


def test_get_top_ceap_spender_default_top_n_is_one():
    with patch.object(router_service, "get_top_ceap_spender", return_value=_dataclass_like({})) as tool:
        execute_tool("get_top_ceap_spender", {"casa": "senado", "ano": 2022})
    tool.assert_called_once_with(casa="senado", ano=2022, top_n=1)


# ----------------------------- list_expense_categories ----------------------------- #

def test_list_expense_categories_dispatch():
    with patch.object(router_service, "list_expense_categories",
                      return_value=_dataclass_like({"total_categorias": 2})) as tool:
        result = execute_tool("list_expense_categories", {"casa": "camara", "incluir_exemplos": False, "ano": 2023})

    tool.assert_called_once_with(casa="camara", incluir_exemplos=False, ano=2023)
    assert result == {"total_categorias": 2}


def test_list_expense_categories_defaults_to_examples():
    with patch.object(router_service, "list_expense_categories", return_value=_dataclass_like({})) as tool:
        execute_tool("list_expense_categories", {"casa": "senado"})
    tool.assert_called_once_with(casa="senado", incluir_exemplos=True, ano=None)


# --------------------------- check_parliamentary_expenses --------------------------- #

def test_expenses_without_parliamentarian_does_not_resolve():
    with patch.object(router_service, "resolve_politician") as resolver, \
         patch.object(router_service, "check_parliamentary_expenses",
                      return_value=_dataclass_like({"valor_max": 900.0})) as tool:
        result = execute_tool(
            "check_parliamentary_expenses", {"casa": "camara", "ano": 2023, "categoria": "Combustíveis"}
        )

    resolver.assert_not_called()
    tool.assert_called_once_with(casa="camara", ano=2023, categoria="Combustíveis", parlamentar_id=None)
    assert result == {"valor_max": 900.0}


def test_expenses_with_numeric_id_passes_through_without_resolving():
    with patch.object(router_service, "resolve_politician") as resolver, \
         patch.object(router_service, "check_parliamentary_expenses", return_value=_dataclass_like({})) as tool:
        execute_tool("check_parliamentary_expenses", {"casa": "camara", "ano": 2023, "parlamentar_id": "204379"})

    resolver.assert_not_called()
    assert tool.call_args.kwargs["parlamentar_id"] == "204379"


def test_expenses_with_name_resolves_camara_before_querying(trace_recorder):
    with patch.object(router_service, "resolve_politician", return_value=RESOLVED_CAMARA) as resolver, \
         patch.object(router_service, "check_parliamentary_expenses", return_value=_dataclass_like({"ok": 1})) as tool:
        result = execute_tool(
            "check_parliamentary_expenses", {"casa": "camara", "ano": 2023, "parlamentar_id": "Fulano de Tal"}
        )

    assert resolver.call_args.kwargs["nome_busca"] == "Fulano de Tal"
    assert resolver.call_args.kwargs["cargo"] == "Deputado Federal"
    assert tool.call_args.kwargs["parlamentar_id"] == "204379"
    assert result == {"ok": 1}
    assert [n for n, _ in trace_recorder.tree()] == ["resolve_politician"]


def test_expenses_with_name_resolves_senado_to_cod_senador():
    with patch.object(router_service, "resolve_politician", return_value=RESOLVED_SENADO) as resolver, \
         patch.object(router_service, "check_parliamentary_expenses", return_value=_dataclass_like({})) as tool:
        execute_tool("check_parliamentary_expenses", {"casa": "senado", "ano": 2023, "parlamentar_id": "Beltrana"})

    assert resolver.call_args.kwargs["cargo"] == "Senador"
    assert tool.call_args.kwargs["parlamentar_id"] == "5012"


@pytest.mark.parametrize("resolution, ambiguous", [(NOT_FOUND, False), (AMBIGUOUS, True)])
def test_expenses_with_unresolved_name_never_calls_data_tool(resolution, ambiguous):
    with patch.object(router_service, "resolve_politician", return_value=resolution), \
         patch.object(router_service, "check_parliamentary_expenses") as tool:
        result = execute_tool(
            "check_parliamentary_expenses", {"casa": "camara", "ano": 2023, "parlamentar_id": "Fulano"}
        )

    tool.assert_not_called()
    assert result["status"] == "entidade_nao_resolvida"
    assert result["ambiguous"] is ambiguous
    assert result["parlamentar_informado"] == "Fulano"


# ---------------------------- get_proposition_vote_result ---------------------------- #

def test_vote_result_dispatch_wraps_list_and_passes_string_id():
    votes = [{"id_votacao": "v1", "aprovado": True}]
    with patch.object(router_service, "get_proposition_vote_result", return_value=votes) as tool:
        result = execute_tool("get_proposition_vote_result", {"casa": "camara", "id_proposicao": 2270800})

    tool.assert_called_once_with(id_proposicao="2270800", casa="camara")
    assert result == {"casa": "camara", "id_proposicao": "2270800", "votacoes": votes}


def test_vote_result_empty_list_is_kept_as_absence_signal():
    with patch.object(router_service, "get_proposition_vote_result", return_value=[]):
        result = execute_tool("get_proposition_vote_result", {"casa": "senado", "id_proposicao": "55"})
    assert result["votacoes"] == []


@pytest.mark.parametrize("args", [{"casa": "camara"}, {"casa": "camara", "id_proposicao": None},
                                  {"casa": "camara", "id_proposicao": "PL 2338/2023"}])
def test_vote_result_without_canonical_id_never_calls_data_tool(args):
    with patch.object(router_service, "get_proposition_vote_result") as tool:
        result = execute_tool("get_proposition_vote_result", args)

    tool.assert_not_called()
    assert result["status"] == "entidade_nao_resolvida"


# ------------------------------ fluxo completo /check ------------------------------ #

def test_check_returns_json_serializable_evidence_from_data_tool():
    chat = ChatResult(content="", tool_calls=[
        {"name": "get_top_ceap_spender", "arguments": {"casa": "camara", "ano": 2023}}])
    judge = {"veredito": "VERDADEIRO", "confianca": "ALTA", "fontes_primarias": ["Câmara dos Deputados"],
             "justificativa": "Conforme a Câmara dos Deputados.", "tempo_julgamento_ms": 1.0}
    with patch.object(router_service, "llm_client") as llm, \
         patch.object(router_service, "get_top_ceap_spender",
                      return_value=_dataclass_like({"gastadores": [{"posicao": 1, "nome_parlamentar": "X"}]})), \
         patch.object(router_service, "_call_judge", return_value=judge):
        llm.chat.return_value = chat
        resp = TestClient(router_service.app).post(
            "/check", json={"claim": "Em 2023, o deputado Pompeo de Mattos gastou mais cota."}
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_usada"] == "get_top_ceap_spender"
    assert data["evidencia_coletada"]["gastadores"][0]["posicao"] == 1


# --------------------- tools de regra institucional (base curada) --------------------- #

RULE = {"encontrado": True, "topico": "sabatina_stf", "resposta_resumida": "Votação secreta.",
        "fonte_normativa": "Constituição Federal, art. 52, III", "fundamentacao": "x", "veredito_regra": "votacao_secreta"}
COVERAGE = {"encontrado": True, "fonte": "tse_prestacao_contas", "tipo_dado": "despesas_campanha_candidatos",
            "disponivel": True, "url_referencia": "https://divulgacandcontas.tse.jus.br", "base_legal": "Lei 9.504/1997",
            "observacao": ""}


def test_check_institutional_rule_dispatch():
    with patch.object(router_service, "check_institutional_rule", return_value=RULE) as tool:
        result = execute_tool("check_institutional_rule", {"topico": "sabatina_stf"})
    tool.assert_called_once_with(topico="sabatina_stf")
    assert result == RULE


def test_check_data_source_coverage_dispatch():
    with patch.object(router_service, "check_data_source_coverage", return_value=COVERAGE) as tool:
        result = execute_tool(
            "check_data_source_coverage",
            {"fonte": "tse_prestacao_contas", "tipo_dado": "despesas_campanha_candidatos"},
        )
    tool.assert_called_once_with(fonte="tse_prestacao_contas", tipo_dado="despesas_campanha_candidatos")
    assert result == COVERAGE


def test_normative_tools_run_on_the_real_curated_base():
    rule = execute_tool("check_institutional_rule", {"topico": "sabatina_stf"})
    assert rule["encontrado"] is True and rule["fonte_normativa"]
    cov = execute_tool("check_data_source_coverage",
                       {"fonte": "portal_transparencia", "tipo_dado": "licitacoes_dados_abertos"})
    assert cov["encontrado"] is True and cov["base_legal"]


def test_normative_tools_never_touch_transactional_data():
    """Regra 4: claim normativa não consulta dado transacional nem resolve entidade."""
    with patch.object(router_service, "resolve_politician") as resolver, \
         patch.object(router_service, "check_parliamentary_expenses") as expenses:
        execute_tool("check_institutional_rule", {"topico": "cota_compra_bens"})
    resolver.assert_not_called()
    expenses.assert_not_called()


def test_unknown_topic_is_not_found_not_invented():
    result = execute_tool("check_institutional_rule", {"topico": "topico_que_nao_existe"})
    assert result["encontrado"] is False
