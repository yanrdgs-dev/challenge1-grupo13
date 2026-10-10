"""Testes do Router Service: LLMClient mockado, guardrails de entrada/saída e orquestração."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.core.llm_client import ChatResult
from src.services import router_service
from src.services.router_service import app

client = TestClient(app)

CLAIM_ESPECIFICA = "O deputado Fulano de Tal é do PL-SP."


def _chat_result(tool_calls=None):
    return ChatResult(
        content="",
        tool_calls=tool_calls or [],
        usage={"input_tokens": 10, "output_tokens": 5},
        provider="ollama",
        model="qwen2.5:7b",
    )


def _judge_response(veredito="VERDADEIRO", fontes=None, justificativa="Conforme a Câmara dos Deputados, confirmado."):
    return {
        "veredito": veredito,
        "confianca": "ALTA",
        "justificativa": justificativa,
        "fontes_primarias": ["Câmara dos Deputados"] if fontes is None else fontes,
        "tempo_julgamento_ms": 12.0,
    }


@pytest.fixture
def mock_llm():
    with patch.object(router_service, "llm_client") as m:
        yield m


def test_happy_path_routes_via_llm_client_and_judges(mock_llm):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "resolve_politician", "arguments": {"nome_busca": "Fulano de Tal"}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"ideCadastro": 1}), \
         patch.object(router_service, "_call_judge", return_value=_judge_response()):
        resp = client.post("/check", json={"claim": CLAIM_ESPECIFICA})

    assert resp.status_code == 200
    data = resp.json()
    assert data["veredito"] == "VERDADEIRO"
    assert data["tool_usada"] == "resolve_politician"
    assert data["evidencia_coletada"] == {"ideCadastro": 1}
    mock_llm.chat.assert_called_once()
    assert mock_llm.chat.call_args.kwargs["tools"] == router_service.TOOLS_CATALOG


def test_llm_failure_returns_503(mock_llm):
    mock_llm.chat.side_effect = RuntimeError("Falha total nos serviços de LLM")
    resp = client.post("/check", json={"claim": CLAIM_ESPECIFICA})
    assert resp.status_code == 503


def test_empty_claim_returns_400(mock_llm):
    resp = client.post("/check", json={"claim": "   "})
    assert resp.status_code == 400
    mock_llm.chat.assert_not_called()


def test_underspecified_claim_is_inconclusive_without_llm_or_tool(mock_llm):
    with patch.object(router_service, "execute_tool") as tool:
        resp = client.post(
            "/check",
            json={"claim": "Um deputado gastou muito dinheiro público recentemente."},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["veredito"] == "INCONCLUSIVO"
    assert data["tool_usada"] is None
    assert data["justificativa"]
    mock_llm.chat.assert_not_called()
    tool.assert_not_called()


def test_rumour_claim_is_inconclusive_without_llm_or_tool(mock_llm):
    with patch.object(router_service, "execute_tool") as tool:
        resp = client.post("/check", json={"claim": "Segundo comentários nas redes sociais, o deputado Fulano votou a favor."})

    assert resp.json()["veredito"] == "INCONCLUSIVO"
    mock_llm.chat.assert_not_called()
    tool.assert_not_called()


def test_partisan_opinion_is_inconclusive_without_llm(mock_llm):
    resp = client.post("/check", json={"claim": "Em quem devo votar para deputado?"})
    assert resp.json()["veredito"] == "INCONCLUSIVO"
    mock_llm.chat.assert_not_called()


def test_output_rail_overrides_verdict_without_tool(mock_llm):
    """Regra 1: veredito FALSO/VERDADEIRO sem tool executada vira INCONCLUSIVO."""
    mock_llm.chat.return_value = _chat_result([])  # roteador não escolheu tool
    with patch.object(router_service, "_call_judge", return_value=_judge_response(veredito="FALSO")):
        resp = client.post("/check", json={"claim": CLAIM_ESPECIFICA})

    data = resp.json()
    assert data["veredito"] == "INCONCLUSIVO"
    assert data["tool_usada"] is None


def test_output_rail_overrides_verdict_when_no_source_can_be_attributed(mock_llm):
    """Sem fonte do judge e sem fonte derivável da tool (nenhum identificador), não há veredito."""
    mock_llm.chat.return_value = _chat_result(
        [{"name": "resolve_politician", "arguments": {"nome_busca": "Fulano de Tal"}}]
    )
    no_ids = {"ideCadastro": None, "cod_senador": None, "sq_candidato": None, "ambiguous": False}
    with patch.object(router_service, "execute_tool", return_value=no_ids), \
         patch.object(router_service, "_call_judge", return_value=_judge_response(veredito="FALSO", fontes=[])):
        resp = client.post("/check", json={"claim": CLAIM_ESPECIFICA})

    assert resp.json()["veredito"] == "INCONCLUSIVO"


def test_judge_unreachable_degrades_to_inconclusive(mock_llm):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "resolve_politician", "arguments": {"nome_busca": "Fulano de Tal"}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"ideCadastro": 1}), \
         patch.object(router_service, "_call_judge", side_effect=Exception("judge fora do ar")):
        resp = client.post("/check", json={"claim": CLAIM_ESPECIFICA})

    assert resp.status_code == 200
    assert resp.json()["veredito"] == "INCONCLUSIVO"


# --------------------------------------------------------------------------- #
# Fonte primária derivada da tool (o judge não precisa citar o órgão corretamente)
# --------------------------------------------------------------------------- #

def _expense_chat(casa="camara"):
    return _chat_result([{"name": "get_top_ceap_spender", "arguments": {"casa": casa, "ano": 2023}}])


def test_verdict_is_kept_when_judge_cites_the_tool_name_as_source(mock_llm):
    """Caso real: o judge pôs o nome da tool em fontes_primarias e o texto sem órgão."""
    mock_llm.chat.return_value = _expense_chat()
    judge = _judge_response(
        veredito="VERDADEIRO",
        fontes=["get_top_ceap_spender"],
        justificativa="A evidência oficial confirma que Pompeo de Mattos gastou mais.",
    )
    with patch.object(router_service, "execute_tool", return_value={"gastadores": [{"posicao": 1}]}), \
         patch.object(router_service, "_call_judge", return_value=judge):
        data = client.post("/check", json={"claim": CLAIM_ESPECIFICA}).json()

    assert data["veredito"] == "VERDADEIRO"
    assert data["fontes_primarias"] == ["Câmara dos Deputados - Dados Abertos (CEAP)"]
    assert "Fonte: Câmara dos Deputados - Dados Abertos (CEAP)." in data["justificativa"]


def test_senate_expense_claim_cites_the_senate_source(mock_llm):
    mock_llm.chat.return_value = _expense_chat("senado")
    judge = _judge_response(veredito="FALSO", fontes=["get_top_ceap_spender"], justificativa="Os dados divergem.")
    with patch.object(router_service, "execute_tool", return_value={"gastadores": []}), \
         patch.object(router_service, "_call_judge", return_value=judge):
        data = client.post("/check", json={"claim": CLAIM_ESPECIFICA}).json()

    assert data["veredito"] == "FALSO"
    assert data["fontes_primarias"] == ["Senado Federal - Dados Abertos (CEAPS)"]


def test_unresolved_entity_evidence_cannot_support_a_verdict(mock_llm):
    """Regra 2: entidade não resolvida nunca sustenta VERDADEIRO/FALSO."""
    mock_llm.chat.return_value = _chat_result(
        [{"name": "check_parliamentary_expenses", "arguments": {"casa": "camara", "ano": 2023, "parlamentar_id": "Fulano"}}]
    )
    evidence = {"status": "entidade_nao_resolvida", "ambiguous": False}
    judge = _judge_response(veredito="FALSO", fontes=["check_parliamentary_expenses"], justificativa="Divergente.")
    with patch.object(router_service, "execute_tool", return_value=evidence), \
         patch.object(router_service, "_call_judge", return_value=judge):
        data = client.post("/check", json={"claim": CLAIM_ESPECIFICA}).json()

    assert data["veredito"] == "INCONCLUSIVO"
    assert data["fontes_primarias"] == []


def test_router_links_generation_to_prompt_version(mock_llm):
    from src.observability.prompts import PromptResult

    prompt_client = object()
    result = PromptResult(
        text="sistema", name="factcheck-router-system", version=3,
        label="production", source="langfuse", prompt_client=prompt_client,
    )
    mock_llm.chat.return_value = _chat_result([])
    with patch.object(router_service, "get_prompt", return_value=result):
        router_service._chat_for_routing("claim qualquer", router_service.TOOLS_CATALOG)

    assert mock_llm.chat.call_args.kwargs["prompt"] is prompt_client


# ------------------------------- data da base no veredito ------------------------------- #

INFO_DATES = {"gerado_em": "2026-10-10T14:21:12+00:00", "fontes": {
    "camara-ceap-2023": {"baixado_em": "2026-10-10T14:13:18+00:00"},
}}


def _check_expenses(mock_llm, evidence, judge=None):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "check_parliamentary_expenses", "arguments": {"casa": "camara", "ano": 2023}}])
    with patch.object(router_service, "execute_tool", return_value=evidence), \
         patch.object(router_service, "_call_judge", return_value=judge or _judge_response()), \
         patch.object(router_service, "load_ingestion_info", return_value=INFO_DATES):
        return client.post("/check", json={"claim": "O deputado Fulano gastou R$ 10 mil em 2023 com combustível."})


def test_verdict_cites_the_base_date_when_the_tool_read_ingested_data(mock_llm):
    resp = _check_expenses(mock_llm, {"qtd_lancamentos": 3, "valor_total": 10.0})
    data = resp.json()
    assert resp.status_code == 200
    assert data["dados_atualizados_em"] == "2026-10-10T14:13:18+00:00"
    assert "Base de dados consultada atualizada em 10/10/2026 às 11:13" in data["justificativa"]


def test_citation_is_identical_for_every_verdict(mock_llm):
    tails = set()
    for verdict in ("VERDADEIRO", "FALSO", "INCONCLUSIVO"):
        data = _check_expenses(mock_llm, {"qtd_lancamentos": 3}, _judge_response(veredito=verdict)).json()
        tails.add(data["justificativa"].split("Base de dados")[-1])
    assert len(tails) == 1  # neutralidade (regra 6): mesma frase para qualquer veredito


def test_no_date_when_the_tool_failed(mock_llm):
    data = _check_expenses(mock_llm, {"erro": "sem dados"}).json()
    assert data["dados_atualizados_em"] is None and "Base de dados consultada" not in data["justificativa"]


def test_no_date_when_the_ingestion_info_is_unavailable(mock_llm):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "check_parliamentary_expenses", "arguments": {"casa": "camara", "ano": 2023}}])
    with patch.object(router_service, "execute_tool", return_value={"qtd_lancamentos": 3}), \
         patch.object(router_service, "_call_judge", return_value=_judge_response()), \
         patch.object(router_service, "load_ingestion_info", return_value=None):
        data = client.post("/check", json={"claim": "O deputado Fulano gastou R$ 10 mil em 2023."}).json()
    assert data["dados_atualizados_em"] is None and "Base de dados consultada" not in data["justificativa"]


def test_frontend_response_shows_the_date_as_a_detail_line():
    from types import SimpleNamespace

    from src.services.frontend_api import to_frontend_response

    response = SimpleNamespace(
        claim="c", veredito="VERDADEIRO", justificativa="t", fontes_primarias=["Câmara"], confianca="ALTA",
        ferramentas_usadas=["check_parliamentary_expenses"], trace_id="abc", regra_acionada=None,
        dados_atualizados_em="2026-10-10T14:13:18+00:00")
    assert any("atualizad" in line.lower() and "10/10/2026" in line for line in to_frontend_response(response).subdetails)
