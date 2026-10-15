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


# ------------------- guarda: nome de parlamentar inventado pelo LLM (regras 2 e 3) ------------------- #

def _route_member_expenses(mock_llm, claim, parlamentar):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "get_member_expenses",
          "arguments": {"casa": "camara", "ano": 2023, "parlamentar": parlamentar, "categoria": "Combustíveis"}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"qtd_lancamentos": 3}) as execute:
        outcome = router_service._route_and_execute(claim)
    return outcome, execute


def test_member_expenses_with_name_invented_by_llm_never_runs_the_tool(mock_llm):
    """A alegação não cita ninguém: o LLM não pode soprar um nome (regra 3 → INCONCLUSIVO)."""
    outcome, execute = _route_member_expenses(
        mock_llm, "quanto ganha um deputado do DF em vale-combustível?", "Nikolas Ferreira"
    )

    execute.assert_not_called()
    assert outcome.evidence["status"] == "entidade_nao_resolvida"
    assert outcome.evidence["parlamentar_informado"] == "Nikolas Ferreira"
    assert outcome.tools_used == []


@pytest.mark.parametrize("claim, parlamentar", [
    ("Quanto o deputado Fraga do DF ganha de vale-combustível?", "Fraga"),
    ("Quanto o deputado ALBERTO FRAGA gastou com combustível?", "Alberto Fraga"),
    ("quanto a senadora Simone Tébet gastou em combustível?", "Simone Tebet"),   # sem acento
])
def test_member_expenses_with_name_present_in_the_claim_runs_the_tool(mock_llm, claim, parlamentar):
    outcome, execute = _route_member_expenses(mock_llm, claim, parlamentar)

    execute.assert_called_once()
    assert outcome.evidence == {"qtd_lancamentos": 3}
    assert outcome.tools_used == ["get_member_expenses"]


@pytest.mark.parametrize("claim, expected_uf", [
    ("Quanto o deputado Fraga do DF gastou com combustível?", "DF"),
    ("Quanto a senadora Fraga de SP gastou com combustível?", "SP"),
    ("Quanto o deputado Fraga (DF) gastou com combustível?", "DF"),
    ("Quanto o deputado Fraga gastou com combustível?", None),
    ("Quanto o deputado Fraga do PL gastou com combustível?", None),   # PL é partido, não UF
])
def test_member_expenses_infers_uf_from_the_claim_when_llm_omits_it(mock_llm, claim, expected_uf):
    _, execute = _route_member_expenses(mock_llm, claim, "Fraga")

    assert execute.call_args.args[1].get("uf") == expected_uf


def test_member_expenses_keeps_uf_chosen_by_llm(mock_llm):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "get_member_expenses",
          "arguments": {"casa": "camara", "ano": 2023, "parlamentar": "Fraga", "uf": "ES"}}]
    )
    with patch.object(router_service, "execute_tool", return_value={}) as execute:
        router_service._route_and_execute("Quanto o deputado Fraga do DF gastou?")

    assert execute.call_args.args[1]["uf"] == "ES"

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


# ------------------- proposição citada formalmente ("PLN 2/2025") nunca fica sem o resolvedor ------------------- #

PLN_CLAIM = "O PLN 2/2025 trata das diretrizes orçamentárias de 2026?"
RESOLVER_CALL = {"name": "resolve_proposition",
                 "arguments": {"casa": "congresso", "sigla_tipo": "PLN", "numero": 2, "ano": 2025}}


@pytest.mark.parametrize("claim, expected", [
    ("O PLN 2/2025 trata das diretrizes?", ("PLN", 2, 2025)),
    ("A PEC 45/2019 foi aprovada?", ("PEC", 45, 2019)),
    ("O PL nº 2630, de 2020, foi aprovado?", ("PL", 2630, 2020)),
    ("O pl 2.630/2020 foi aprovado?", ("PL", 2630, 2020)),
    ("A MPV 1.303 /2025 caducou?", ("MPV", 1303, 2025)),
    ("Quanto o deputado Fraga gastou em 2023?", None),
    ("O candidato de número 22/2024 foi eleito?", None),
])
def test_cited_proposition_is_extracted_from_the_claim(claim, expected):
    assert router_service._cited_proposition(claim) == expected


def test_claim_citing_a_proposition_retries_with_resolver_when_llm_picks_unrelated_tool(mock_llm):
    mock_llm.chat.side_effect = [
        _chat_result([{"name": "get_campaign_finances", "arguments": {"ano": 2026}}]),
        _chat_result([RESOLVER_CALL]),
    ]
    with patch.object(router_service, "execute_tool", return_value={"id_proposicao": 168120}) as execute:
        outcome = router_service._route_and_execute(PLN_CLAIM)

    assert execute.call_args.args[0] == "resolve_proposition"
    assert outcome.tool_name == "resolve_proposition"
    assert mock_llm.chat.call_args_list[1].kwargs["tools"] == router_service._RESOLVER_ONLY_CATALOG


def test_claim_citing_a_proposition_retries_when_llm_picks_no_tool(mock_llm):
    mock_llm.chat.side_effect = [_chat_result([]), _chat_result([RESOLVER_CALL])]
    with patch.object(router_service, "execute_tool", return_value={"id_proposicao": 168120}) as execute:
        router_service._route_and_execute(PLN_CLAIM)

    assert execute.call_args.args[0] == "resolve_proposition"


def test_claim_citing_a_proposition_falls_back_to_the_cited_numbers_when_retry_also_fails(mock_llm):
    """O resolvedor roda com sigla/número/ano da própria alegação, nunca com ID soprado pelo LLM."""
    mock_llm.chat.side_effect = [_chat_result([]), _chat_result([])]
    with patch.object(router_service, "execute_tool", return_value={"id_proposicao": 168120}) as execute:
        router_service._route_and_execute(PLN_CLAIM)

    assert execute.call_args.args == (
        "resolve_proposition", {"casa": "congresso", "sigla_tipo": "PLN", "numero": 2, "ano": 2025}
    )


def test_claim_citing_a_proposition_keeps_the_llm_choice_when_it_is_already_proposition_related(mock_llm):
    mock_llm.chat.return_value = _chat_result([RESOLVER_CALL])
    with patch.object(router_service, "execute_tool", return_value={"id_proposicao": 1}):
        router_service._route_and_execute(PLN_CLAIM)

    mock_llm.chat.assert_called_once()


def test_claim_without_proposition_citation_never_forces_the_resolver(mock_llm):
    mock_llm.chat.return_value = _chat_result([])
    outcome = router_service._route_and_execute("O céu é azul?")

    assert outcome.tool_name is None
    mock_llm.chat.assert_called_once()


def test_claim_citing_a_proposition_falls_back_to_cited_numbers_when_retry_call_fails(mock_llm):
    """Se a segunda chamada ao LLM falhar (timeout), a alegação ainda é resolvida pelos números citados."""
    mock_llm.chat.side_effect = [_chat_result([]), RuntimeError("timed out"), RuntimeError("timed out")]
    with patch.object(router_service, "execute_tool", return_value={"id_proposicao": 168120}) as execute:
        router_service._route_and_execute(PLN_CLAIM)

    assert execute.call_args.args[0] == "resolve_proposition"
    assert execute.call_args.args[1]["numero"] == 2


def test_resolver_call_from_retry_without_casa_gets_the_default_casa(mock_llm):
    """O LLM às vezes omite 'casa' no resolvedor; a busca formal vale para as duas Casas (congresso)."""
    mock_llm.chat.side_effect = [
        _chat_result([]),
        _chat_result([{"name": "resolve_proposition", "arguments": {"sigla_tipo": "PLN", "numero": 2, "ano": 2025}}]),
    ]
    with patch.object(router_service, "execute_tool", return_value={"id_proposicao": 168120}) as execute:
        router_service._route_and_execute(PLN_CLAIM)

    assert execute.call_args.args[1] == {"casa": "congresso", "sigla_tipo": "PLN", "numero": 2, "ano": 2025}


# ------------------- "quem mais gastou" sem campanha/eleição não é gasto de campanha ------------------- #

COTA_CLAIM = "Quem mais gastou em 2022?"
CAMPAIGN_CALL = {"name": "get_top_campaign_finances",
                 "arguments": {"cargo": "Deputado Federal", "ano": 2022, "metrica": "despesas_contratadas"}}
CEAP_CALL = {"name": "get_top_ceap_spender", "arguments": {"casa": "camara", "ano": 2022}}


@pytest.mark.parametrize("claim", [
    "Quem mais gastou em 2022?",
    "Quem mais gastou a cota parlamentar em 2022?",
    "Quanto o deputado Fraga gastou com combustível em 2022?",
])
def test_campaign_tool_without_electoral_cue_in_the_claim_is_rerouted_to_the_quota_tools(mock_llm, claim):
    mock_llm.chat.side_effect = [_chat_result([CAMPAIGN_CALL]), _chat_result([CEAP_CALL])]
    with patch.object(router_service, "execute_tool", return_value={"gastadores": []}) as execute:
        outcome = router_service._route_and_execute(claim)

    retry_tools = {t["function"]["name"] for t in mock_llm.chat.call_args_list[1].kwargs["tools"]}
    # só tools de cota: o modelo, sem a de campanha, escolhe outra do TSE e inventa candidatos
    assert not retry_tools & {"get_campaign_finances", "get_top_campaign_finances", "compare_candidates",
                              "get_election_result", "resolve_candidate"}
    assert "get_top_ceap_spender" in retry_tools
    assert outcome.tool_name == "get_top_ceap_spender"
    assert execute.call_args.args[0] == "get_top_ceap_spender"


@pytest.mark.parametrize("claim", [
    "Quem mais gastou na campanha para presidente em 2022?",
    "Qual candidato a governador mais arrecadou em 2022?",
    "O candidato Fulano declarou gastos de campanha de R$ 1 milhão em 2022?",
    "Quanto a eleição de 2022 custou aos candidatos ao Senado?",
])
def test_campaign_tool_with_electoral_cue_is_kept(mock_llm, claim):
    mock_llm.chat.return_value = _chat_result([CAMPAIGN_CALL])
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        router_service._route_and_execute(claim)

    mock_llm.chat.assert_called_once()
    assert execute.call_args.args[0] == "get_top_campaign_finances"


def test_rerouted_claim_that_gets_no_tool_stays_without_evidence(mock_llm):
    mock_llm.chat.side_effect = [_chat_result([CAMPAIGN_CALL]), _chat_result([])]
    with patch.object(router_service, "execute_tool") as execute:
        outcome = router_service._route_and_execute(COTA_CLAIM)

    execute.assert_not_called()
    assert outcome.tool_name is None


# ------------------- sem tool escolhida o julgador não é chamado (regra 1: nada de resposta da memória) ------------------- #

def test_no_tool_chosen_never_calls_the_judge_and_answers_inconclusive(mock_llm):
    """'O que é a PEC da reforma tributária?': sem tool não há evidência; o juiz explicaria da memória do modelo."""
    mock_llm.chat.return_value = _chat_result([])
    with patch.object(router_service, "_call_judge") as judge:
        resp = client.post("/check", json={"claim": "O que é a PEC da reforma tributária?"})

    judge.assert_not_called()
    data = resp.json()
    assert resp.status_code == 200
    assert data["veredito"] == "INCONCLUSIVO"
    assert data["tool_usada"] is None and data["ferramentas_usadas"] == []
    assert data["regra_acionada"] == "sem_ferramenta_aplicavel"
    assert data["fontes_primarias"] == []
    assert "evidência" in data["justificativa"].lower()


def test_no_tool_chosen_text_does_not_explain_anything_from_the_model_memory(mock_llm):
    mock_llm.chat.return_value = _chat_result([])
    mock_llm.chat.return_value.content = "A PEC da reforma tributária é uma proposta que unifica impostos..."
    with patch.object(router_service, "_call_judge"):
        data = client.post("/check", json={"claim": "O que é a PEC da reforma tributária?"}).json()

    assert "unifica" not in data["justificativa"]


def test_chosen_tool_with_failed_evidence_still_goes_to_the_judge(mock_llm):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "resolve_politician", "arguments": {"nome_busca": "Fulano de Tal"}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"erro": "x"}), \
         patch.object(router_service, "_call_judge", return_value=_judge_response(veredito="INCONCLUSIVO")) as judge:
        client.post("/check", json={"claim": CLAIM_ESPECIFICA})

    judge.assert_called_once()


# ------------------- tramitação/apensamento: o LLM para no resolvedor, o roteador completa ------------------- #

@pytest.mark.parametrize("claim, expected_tool", [
    ("Em que comissões já tramitou o PL 2630/2020?", "get_proposition_tramitation_history"),
    ("O PL 2630/2020 passou por alguma comissão temática?", "get_proposition_tramitation_history"),
    ("Em que fase está a tramitação da PEC 45/2019?", "get_proposition_tramitation_history"),
    ("A PEC 45/2019 está apensada a outra proposição?", "check_bill_apensamentos"),
    ("O PL 2630/2020 foi anexado a outro projeto?", "check_bill_apensamentos"),
])
def test_resolver_choice_is_upgraded_to_tramitation_tool_when_claim_asks_about_it(mock_llm, claim, expected_tool):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "resolve_proposition",
          "arguments": {"casa": "congresso", "sigla_tipo": "PL", "numero": 2630, "ano": 2020}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        outcome = router_service._route_and_execute(claim)

    assert execute.call_args.args[0] == expected_tool
    assert execute.call_args.args[1] == {"casa": "congresso", "sigla_tipo": "PL", "numero": 2630, "ano": 2020}
    assert outcome.tool_name == expected_tool and outcome.tools_used == [expected_tool]


@pytest.mark.parametrize("claim", [
    "O PL 2630/2020 foi aprovado pelo Plenário?",
    "A PEC 45/2019 é da Reforma Tributária?",
])
def test_resolver_choice_is_kept_when_claim_is_not_about_tramitation(mock_llm, claim):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "resolve_proposition",
          "arguments": {"casa": "congresso", "sigla_tipo": "PL", "numero": 2630, "ano": 2020}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"id_proposicao": 1, "casa": "camara"}) as execute:
        router_service._route_and_execute(claim)

    assert execute.call_args_list[0].args[0] == "resolve_proposition"


def test_tramitation_tool_chosen_by_llm_is_kept_and_not_redirected_to_resolver(mock_llm):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "get_proposition_tramitation_history",
          "arguments": {"casa": "camara", "sigla_tipo": "PEC", "numero": 45, "ano": 2019}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        router_service._route_and_execute("Em que fase está a tramitação da PEC 45/2019?")

    mock_llm.chat.assert_called_once()
    assert execute.call_args.args[0] == "get_proposition_tramitation_history"


# ------------------- roteamento em duas etapas (categoria → tools da categoria) ------------------- #

def _tool_names(call):
    return {t["function"]["name"] for t in call.kwargs["tools"]}


@pytest.fixture
def two_stage(monkeypatch):
    monkeypatch.setenv("ROUTER_TWO_STAGE", "true")


def test_two_stage_rule_decided_category_restricts_the_catalog_with_a_single_llm_call(mock_llm, two_stage):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "resolve_proposition", "arguments": {"casa": "camara", "sigla_tipo": "PL", "numero": 2630, "ano": 2020}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"id_proposicao": 1, "casa": "camara"}):
        router_service._route_and_execute("O PL 2630/2020 foi aprovado pelo Plenário?")

    mock_llm.chat.assert_called_once()
    names = _tool_names(mock_llm.chat.call_args)
    assert "resolve_proposition" in names and "check_institutional_rule" in names
    assert not names & {"get_election_result", "get_top_ceap_spender", "compare_candidates"}


def test_two_stage_asks_the_llm_for_the_category_when_rules_do_not_decide(mock_llm, two_stage):
    mock_llm.chat.side_effect = [
        _chat_result_with_content('{"categoria": "COTA_PARLAMENTAR"}'),
        _chat_result([{"name": "get_top_ceap_spender", "arguments": {"casa": "camara", "ano": 2022}}]),
    ]
    with patch.object(router_service, "execute_tool", return_value={"gastadores": []}) as execute:
        router_service._route_and_execute("Quem mais gastou em 2022?")

    classify_call, route_call = mock_llm.chat.call_args_list
    assert classify_call.kwargs["json_mode"] is True and "tools" not in classify_call.kwargs
    assert "get_top_ceap_spender" in _tool_names(route_call)
    assert not _tool_names(route_call) & {"get_election_result", "resolve_proposition"}
    assert execute.call_args.args[0] == "get_top_ceap_spender"


def test_two_stage_keeps_the_full_catalog_when_the_classification_fails(mock_llm, two_stage):
    mock_llm.chat.side_effect = [RuntimeError("timed out"), _chat_result([])]
    router_service._route_and_execute("Quem mais gastou em 2022?")

    assert _tool_names(mock_llm.chat.call_args_list[1]) == {t["function"]["name"] for t in router_service.TOOLS_CATALOG}


def test_two_stage_can_be_turned_off(mock_llm, monkeypatch):
    monkeypatch.setenv("ROUTER_TWO_STAGE", "false")
    mock_llm.chat.return_value = _chat_result([])
    router_service._route_and_execute("Quem mais gastou em 2022?")

    mock_llm.chat.assert_called_once()
    assert mock_llm.chat.call_args.kwargs["tools"] == router_service.TOOLS_CATALOG


def _chat_result_with_content(content):
    result = _chat_result([])
    result.content = content
    return result


# ------------------- compare_candidates com um só candidato vira a tool de um candidato ------------------- #

def _compare_call(**overrides):
    args = {"ano": 2022, "candidatos": ["Lula"], "metrica": "votos_validos", "turno": 2, "cargo": "Presidente"}
    args.update(overrides)
    return {"name": "compare_candidates", "arguments": args}


@pytest.mark.parametrize("metrica, expected_tool", [
    ("votos_validos", "get_candidate_votes"),
    ("patrimonio", "get_candidate_assets"),
    ("receitas", "get_campaign_finances"),
    ("despesas_contratadas", "get_campaign_finances"),
])
def test_compare_with_a_single_candidate_is_repaired_to_the_single_candidate_tool(mock_llm, metrica, expected_tool):
    mock_llm.chat.return_value = _chat_result([_compare_call(metrica=metrica)])
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        outcome = router_service._route_and_execute(
            "No segundo turno da eleição para Presidente de 2022, Lula recebeu 60.345.999 votos válidos."
        )

    assert execute.call_args.args[0] == expected_tool and outcome.tool_name == expected_tool
    args = execute.call_args.args[1]
    assert args["nome_candidato"] == "Lula" and args["ano"] == 2022 and args["cargo"] == "Presidente"
    assert "candidatos" not in args and "metrica" not in args
    if expected_tool == "get_candidate_votes":
        assert args["turno"] == 2
    else:
        assert "turno" not in args


def test_compare_with_two_candidates_is_left_alone(mock_llm):
    mock_llm.chat.return_value = _chat_result([_compare_call(candidatos=["Lula", "Simone Tebet"])])
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        router_service._route_and_execute("Lula teve mais votos que Simone Tebet em 2022?")

    assert execute.call_args.args[0] == "compare_candidates"


def test_compare_with_a_single_candidate_keeps_uf_to_disambiguate(mock_llm):
    mock_llm.chat.return_value = _chat_result(
        [_compare_call(candidatos=["Tarcísio de Freitas"], turno=1, cargo="Governador", uf="SP")]
    )
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        router_service._route_and_execute("Tarcísio de Freitas foi o mais votado para governador de SP em 2022.")

    assert execute.call_args.args[1]["uf"] == "SP"


def test_routing_prompt_gets_the_tool_hint_for_clear_wording(mock_llm):
    mock_llm.chat.return_value = _chat_result([])
    router_service._route_and_execute("Em 2022, Lula declarou ao TSE bens que somam mais de 7 milhões de reais.")

    system = mock_llm.chat.call_args.args[0][0]["content"]
    assert "get_candidate_assets" in system.split("Dica de roteamento")[-1]


def test_routing_prompt_has_no_hint_without_clear_wording(mock_llm):
    mock_llm.chat.return_value = _chat_result([])
    router_service._route_and_execute("Quem mais gastou em 2022?")

    assert "Dica de roteamento" not in mock_llm.chat.call_args.args[0][0]["content"]


# ------------------- tool dita pela redação: se o LLM escolhe outra, refaz só com ela ------------------- #

ASSETS_CLAIM = "Em 2022, Lula declarou ao TSE bens que somam mais de 7 milhões de reais."


def test_llm_choice_that_differs_from_the_hinted_tool_is_retried_with_only_the_hinted_tool(mock_llm):
    mock_llm.chat.side_effect = [
        _chat_result([{"name": "check_cash_and_special_assets", "arguments": {"nome_candidato": "Lula", "ano": 2022}}]),
        _chat_result([{"name": "get_candidate_assets", "arguments": {"nome_candidato": "Lula", "ano": 2022}}]),
    ]
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        outcome = router_service._route_and_execute(ASSETS_CLAIM)

    retry = mock_llm.chat.call_args_list[1]
    assert [t["function"]["name"] for t in retry.kwargs["tools"]] == ["get_candidate_assets"]
    assert execute.call_args.args[0] == "get_candidate_assets" and outcome.tool_name == "get_candidate_assets"


def test_llm_choice_equal_to_the_hinted_tool_is_not_retried(mock_llm):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "get_candidate_assets", "arguments": {"nome_candidato": "Lula", "ano": 2022}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}):
        router_service._route_and_execute(ASSETS_CLAIM)

    mock_llm.chat.assert_called_once()


def test_hinted_retry_that_fails_keeps_the_original_choice(mock_llm):
    mock_llm.chat.side_effect = [
        _chat_result([{"name": "check_cash_and_special_assets", "arguments": {"nome_candidato": "Lula", "ano": 2022}}]),
        _chat_result([]),
    ]
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        router_service._route_and_execute(ASSETS_CLAIM)

    assert execute.call_args.args[0] == "check_cash_and_special_assets"


def test_no_tool_with_a_hint_is_retried_with_the_hinted_tool(mock_llm):
    mock_llm.chat.side_effect = [
        _chat_result([]),
        _chat_result([{"name": "get_candidate_assets", "arguments": {"nome_candidato": "Lula", "ano": 2022}}]),
    ]
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        router_service._route_and_execute(ASSETS_CLAIM)

    assert execute.call_args.args[0] == "get_candidate_assets"


def test_comparison_between_candidates_is_never_replaced_by_the_hinted_single_candidate_tool(mock_llm):
    mock_llm.chat.return_value = _chat_result([{"name": "compare_candidates", "arguments": {
        "candidatos": ["Lula", "Simone Tebet"], "ano": 2022, "metrica": "patrimonio"}}])
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        router_service._route_and_execute("Em 2022, Lula declarou mais patrimônio do que Simone Tebet.")

    mock_llm.chat.assert_called_once()
    assert execute.call_args.args[0] == "compare_candidates"


# ------------------- turno dito na alegação, esquecido pelo LLM ------------------- #

@pytest.mark.parametrize("claim, turno", [
    ("Em 2022, Jair Bolsonaro venceu o segundo turno da eleição presidencial.", 2),
    ("Lula foi o mais votado no 2º turno de 2022.", 2),
    ("Lula foi o mais votado no 2o turno de 2022.", 2),
    ("Lula foi o mais votado no primeiro turno de 2022.", 1),
    ("Lula foi o mais votado no 1º turno de 2022.", 1),
])
@pytest.mark.parametrize("tool, base_args", [
    ("get_election_result", {"cargo": "Presidente", "ano": 2022}),
    ("get_candidate_votes", {"nome_candidato": "Lula", "ano": 2022}),
    ("compare_candidates", {"candidatos": ["Lula", "Jair Bolsonaro"], "ano": 2022, "metrica": "votos_validos"}),
])
def test_turno_written_in_the_claim_is_filled_when_the_llm_forgets_it(mock_llm, claim, turno, tool, base_args):
    mock_llm.chat.return_value = _chat_result([{"name": tool, "arguments": dict(base_args)}])
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        router_service._route_and_execute(claim)

    assert execute.call_args.args[1]["turno"] == turno


def test_turno_chosen_by_the_llm_is_never_overridden(mock_llm):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "get_election_result", "arguments": {"cargo": "Presidente", "ano": 2022, "turno": 1}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        router_service._route_and_execute("Em 2022, Jair Bolsonaro venceu o segundo turno.")

    assert execute.call_args.args[1]["turno"] == 1


def test_turno_is_not_invented_when_the_claim_does_not_say_it(mock_llm):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "get_election_result", "arguments": {"cargo": "Presidente", "ano": 2022}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        router_service._route_and_execute("Em 2022, Lula foi o mais votado para presidente.")

    assert "turno" not in execute.call_args.args[1]


def test_turno_is_not_added_to_tools_that_do_not_take_it(mock_llm):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "get_candidate_assets", "arguments": {"nome_candidato": "Lula", "ano": 2022}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        router_service._route_and_execute("No segundo turno de 2022, Lula declarou 7 milhões em bens.")

    assert "turno" not in execute.call_args.args[1]


# ------------------- proposição por nome popular: o resolvedor sempre roda, na Casa que a alegação cita ------------------- #

SENADO_PEC_CLAIM = "O Senado aprovou, em votação nominal, o texto-base da PEC da Reforma Tributária em 2023."
MARCO_CLAIM = "A votação do Marco Temporal na Câmara dos Deputados em 2023 foi unânime, sem nenhum deputado votando contra."


def _resolver_call(**args):
    return {"name": "resolve_proposition", "arguments": {"termo_busca": "PEC da Reforma Tributária", **args}}


def test_proposition_claim_without_a_tool_is_retried_with_the_resolver_only(mock_llm, two_stage):
    mock_llm.chat.side_effect = [_chat_result([]), _chat_result([_resolver_call(casa="senado")])]
    with patch.object(router_service, "execute_tool", return_value={"id_proposicao": 1, "casa": "senado"}):
        router_service._route_and_execute(SENADO_PEC_CLAIM)

    retry = mock_llm.chat.call_args_list[1]
    assert [t["function"]["name"] for t in retry.kwargs["tools"]] == ["resolve_proposition"]


@pytest.mark.parametrize("claim, casa_from_llm, expected", [
    (SENADO_PEC_CLAIM, "congresso", "senado"),
    (MARCO_CLAIM, "congresso", "camara"),
    (MARCO_CLAIM, None, "camara"),
    ("O Senado e a Câmara aprovaram a PEC da Reforma Tributária em 2023.", "congresso", "congresso"),
    ("A PEC da Reforma Tributária foi aprovada em 2023.", "congresso", "congresso"),
    (SENADO_PEC_CLAIM, "camara", "camara"),                 # a escolha explícita do LLM nunca é trocada
])
def test_resolver_house_comes_from_the_house_named_in_the_claim(mock_llm, claim, casa_from_llm, expected):
    args = {} if casa_from_llm is None else {"casa": casa_from_llm}
    mock_llm.chat.return_value = _chat_result([_resolver_call(**args)])
    with patch.object(router_service, "execute_tool", return_value={"id_proposicao": 1}) as execute:
        router_service._route_and_execute(claim)

    assert execute.call_args.args[1]["casa"] == expected


def test_no_tool_outside_the_proposition_category_is_not_forced_to_the_resolver(mock_llm):
    mock_llm.chat.return_value = _chat_result([])
    outcome = router_service._route_and_execute("O céu é azul?")

    mock_llm.chat.assert_called_once()
    assert outcome.tool_name is None


@pytest.mark.parametrize("claim", [
    "Qual é o status atual da PEC da Dosimetria no Senado?",
    "Em que pé está a PEC 45/2019?",
    "Qual o andamento do PL 2630/2020?",
])
def test_status_and_progress_wording_upgrades_the_resolver_to_the_tramitation_tool(mock_llm, claim):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "resolve_proposition", "arguments": {"casa": "senado", "termo_busca": "PEC da Dosimetria"}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        router_service._route_and_execute(claim)

    assert execute.call_args.args[0] == "get_proposition_tramitation_history"


# ------------------- tempo relativo resolvido pela data de hoje ------------------- #

from datetime import date  # noqa: E402


@pytest.fixture
def fixed_today(monkeypatch):
    monkeypatch.setattr(router_service, "_today", lambda: date(2026, 10, 15))


def test_routing_prompt_carries_todays_date(mock_llm, fixed_today):
    mock_llm.chat.return_value = _chat_result([])
    router_service._route_and_execute("Quem mais gastou a cota parlamentar da Câmara neste ano?")

    system = mock_llm.chat.call_args.args[0][0]["content"]
    assert "Data de hoje: 2026-10-15" in system
    assert "2026" in system.split("Data de hoje")[-1]


@pytest.mark.parametrize("claim", [
    "Neste ano, o deputado que mais gastou a cota parlamentar foi Fulano.",
    "Este ano o deputado que mais gastou a cota parlamentar foi Fulano.",
    "No ano atual, o deputado que mais gastou a cota parlamentar foi Fulano.",
    "Atualmente o deputado que mais gastou a cota parlamentar é Fulano.",
])
def test_missing_year_is_filled_with_the_current_year_when_the_claim_says_this_year(mock_llm, fixed_today, claim):
    mock_llm.chat.return_value = _chat_result([{"name": "get_top_ceap_spender", "arguments": {"casa": "camara"}}])
    with patch.object(router_service, "execute_tool", return_value={"gastadores": []}) as execute:
        router_service._route_and_execute(claim)

    assert execute.call_args.args[1]["ano"] == 2026


def test_year_chosen_by_the_llm_is_never_overridden_by_the_current_year(mock_llm, fixed_today):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "get_top_ceap_spender", "arguments": {"casa": "camara", "ano": 2023}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"gastadores": []}) as execute:
        router_service._route_and_execute("Neste ano, o deputado que mais gastou a cota foi Fulano.")

    assert execute.call_args.args[1]["ano"] == 2023


def test_year_is_not_invented_when_the_claim_does_not_say_this_year(mock_llm, fixed_today):
    mock_llm.chat.return_value = _chat_result([{"name": "get_top_ceap_spender", "arguments": {"casa": "camara"}}])
    with patch.object(router_service, "execute_tool", return_value={"gastadores": []}) as execute:
        router_service._route_and_execute("O deputado que mais gastou a cota parlamentar foi Fulano.")

    assert "ano" not in execute.call_args.args[1]


def test_current_year_is_not_added_to_tools_without_a_year_parameter(mock_llm, fixed_today):
    mock_llm.chat.return_value = _chat_result(
        [{"name": "check_institutional_rule", "arguments": {"topico": "veto_presidencial"}}]
    )
    with patch.object(router_service, "execute_tool", return_value={"encontrado": True}) as execute:
        router_service._route_and_execute("Neste ano, o veto presidencial pode ser derrubado pelo Congresso.")

    assert "ano" not in execute.call_args.args[1]
