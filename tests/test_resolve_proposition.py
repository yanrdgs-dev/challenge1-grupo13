"""Testes unitários para a tool resolve_proposition (T007, T008, T009).

Atende rigorosamente ao Princípio VII (TDD) e Princípio VIII (isolamento 100% offline via mocks).
Zero requisições de rede reais durante a execução dos testes.
"""

import httpx
import pytest

from src.tools.legislative_client import LegislativeClient
from src.tools.resolve_proposition import resolve_proposition


@pytest.fixture
def mock_camara_pl2630():
    """Mock da API da Câmara para o PL 2630/2020 (PL das Fake News - Claim 4)."""
    payload = {
        "dados": [
            {
                "id": 2253965,
                "uri": "https://dadosabertos.camara.leg.br/api/v2/proposicoes/2253965",
                "siglaTipo": "PL",
                "codTipo": 139,
                "numero": 2630,
                "ano": 2020,
                "ementa": "Institui a Lei Brasileira de Liberdade, Responsabilidade e Transparência na Internet.",
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "dadosabertos.camara.leg.br" in request.url.host
        assert request.url.params.get("siglaTipo") == "PL"
        assert request.url.params.get("numero") == "2630"
        assert request.url.params.get("ano") == "2020"
        return httpx.Response(200, json=payload)

    return LegislativeClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def mock_senado_pec45():
    """Mock da API do Senado para a PEC 45/2019 (Reforma Tributária - Claim 5)."""
    payload = {
        "PesquisaBasicaMateria": {
            "Materias": {
                "Materia": [
                    {
                        "Codigo": 137350,
                        "IdentificacaoProcesso": 137350,
                        "DescricaoIdentificacao": "PEC 45/2019",
                        "Sigla": "PEC",
                        "Numero": 45,
                        "Ano": 2019,
                        "Ementa": "Altera o Sistema Tributário Nacional e dá outras providências.",
                    }
                ]
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "legis.senado.leg.br" in request.url.host
        assert request.url.params.get("sigla") == "PEC"
        assert request.url.params.get("numero") == "45"
        assert request.url.params.get("ano") == "2019"
        return httpx.Response(200, json=payload)

    return LegislativeClient(transport=httpx.MockTransport(handler))


def test_resolve_proposition_camara_exact(mock_camara_pl2630):
    """T007: Valida resolução exata na Câmara (PL 2630/2020) com resposta mockada."""
    result = resolve_proposition(
        casa="camara",
        sigla_tipo="PL",
        numero=2630,
        ano=2020,
        client=mock_camara_pl2630,
    )

    assert result["ambiguous"] is False
    assert result["id_proposicao"] == 2253965
    assert result["sigla_tipo"] == "PL"
    assert result["numero"] == 2630
    assert result["ano"] == 2020
    assert result["casa"] == "camara"
    assert "Liberdade, Responsabilidade" in (result["ementa"] or "")
    assert result["candidatos"] == []
    assert result["match_score"] == 100.0


def test_resolve_proposition_senado_exact(mock_senado_pec45):
    """T008: Valida resolução exata no Senado (PEC 45/2019) com resposta mockada."""
    result = resolve_proposition(
        casa="senado",
        sigla_tipo="PEC",
        numero=45,
        ano=2019,
        client=mock_senado_pec45,
    )

    assert result["ambiguous"] is False
    assert result["id_proposicao"] == 137350
    assert result["sigla_tipo"] == "PEC"
    assert result["numero"] == 45
    assert result["ano"] == 2019
    assert result["casa"] == "senado"
    assert "Sistema Tributário Nacional" in (result["ementa"] or "")
    assert result["candidatos"] == []
    assert result["match_score"] == 100.0


def test_resolve_proposition_contract_keys(mock_camara_pl2630):
    """T009: Valida conformidade estrita de chaves com o JSON Schema do contrato."""
    result = resolve_proposition(
        casa="camara",
        sigla_tipo="PL",
        numero=2630,
        ano=2020,
        client=mock_camara_pl2630,
    )

    expected_keys = {
        "id_proposicao",
        "sigla_tipo",
        "numero",
        "ano",
        "ementa",
        "casa",
        "ambiguous",
        "candidatos",
        "match_score",
    }
    assert set(result.keys()) == expected_keys
    assert isinstance(result["ambiguous"], bool)
    assert isinstance(result["candidatos"], list)


def test_resolve_proposition_invalid_casa_and_missing_params():
    """Valida validação defensiva para casa inexistente ou ausência de critérios mínimos (T012)."""
    # Casa inválida
    res_inv = resolve_proposition(casa="invalida", sigla_tipo="PL", numero=10)
    assert res_inv["id_proposicao"] is None
    assert res_inv["ambiguous"] is False
    assert res_inv["casa"] == ""

    # Sem parâmetros mínimos (sem sigla+numero e sem termo_busca)
    res_vazia = resolve_proposition(casa="camara")
    assert res_vazia["id_proposicao"] is None
    assert res_vazia["ambiguous"] is False
    assert res_vazia["casa"] == "camara"


def test_resolve_proposition_popular_name_marco_temporal():
    """T014: Valida resolução por nome popular / tema na ementa (Marco Temporal - Claim 15)."""
    payload = {
        "dados": [
            {
                "id": 490,
                "siglaTipo": "PL",
                "numero": 490,
                "ano": 2007,
                "ementa": "Altera a Lei nº 6.001, estabelecendo o marco temporal para demarcação de terras indígenas.",
            },
            {
                "id": 9999,
                "siglaTipo": "PL",
                "numero": 9999,
                "ano": 2021,
                "ementa": "Dispõe sobre o plantio de soja e milho no Centro-Oeste sem relação direta.",
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "Marco Temporal" in request.url.params.get("keywords", "")
        return httpx.Response(200, json=payload)

    client = LegislativeClient(transport=httpx.MockTransport(handler))
    result = resolve_proposition(
        casa="camara",
        termo_busca="Marco Temporal",
        client=client,
    )

    assert result["ambiguous"] is False
    assert result["id_proposicao"] == 490
    assert result["sigla_tipo"] == "PL"
    assert result["numero"] == 490
    assert result["match_score"] is not None
    assert result["match_score"] >= 80.0
    assert result["candidatos"] == []


def test_resolve_proposition_not_found():
    """T015: Valida resposta estruturada quando a proposição inexiste na API."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"dados": []})

    client = LegislativeClient(transport=httpx.MockTransport(handler))
    result = resolve_proposition(
        casa="camara",
        sigla_tipo="PL",
        numero=999999,
        ano=2020,
        client=client,
    )

    assert result["ambiguous"] is False
    assert result["id_proposicao"] is None
    assert result["sigla_tipo"] is None
    assert result["ementa"] is None
    assert result["candidatos"] == []
    assert result["casa"] == "camara"


def test_resolve_proposition_ambiguity_generic_terms():
    """T018: Valida detecção de ambiguidade em termos genéricos (segurança pública - Claim 26)."""
    payload = {
        "PesquisaBasicaMateria": {
            "Materias": {
                "Materia": [
                    {
                        "Codigo": 101,
                        "Sigla": "PL",
                        "Numero": 1001,
                        "Ano": 2022,
                        "Ementa": "Altera regras do Sistema Único de Segurança Pública.",
                    },
                    {
                        "Codigo": 102,
                        "Sigla": "PL",
                        "Numero": 1002,
                        "Ano": 2023,
                        "Ementa": "Cria diretrizes nacionais para a segurança pública integrada.",
                    },
                    {
                        "Codigo": 103,
                        "Sigla": "PEC",
                        "Numero": 33,
                        "Ano": 2021,
                        "Ementa": "Modifica o artigo 144 sobre as forças de segurança pública.",
                    },
                ]
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "segurança pública" in request.url.params.get("palavra", "")
        return httpx.Response(200, json=payload)

    client = LegislativeClient(transport=httpx.MockTransport(handler))
    result = resolve_proposition(
        casa="senado",
        termo_busca="segurança pública",
        client=client,
    )

    assert result["ambiguous"] is True
    assert result["id_proposicao"] is None
    assert result["casa"] == "senado"
    assert len(result["candidatos"]) >= 2
    # Valida estrutura de cada candidato do array
    for cand in result["candidatos"]:
        assert "id_proposicao" in cand
        assert "sigla_tipo" in cand
        assert "numero" in cand
        assert "ano" in cand
        assert "ementa" in cand
        assert cand["casa"] == "senado"


def test_resolve_proposition_timeout_tolerance():
    """T019: Valida tolerância e degradação graciosa em caso de ConnectTimeout (Princípio VIII)."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Connect timeout mock após 5.0s")

    client = LegislativeClient(transport=httpx.MockTransport(handler))
    result = resolve_proposition(
        casa="camara",
        sigla_tipo="PL",
        numero=1234,
        ano=2024,
        client=client,
    )

    # Não deve subir exceção não tratada
    assert result["ambiguous"] is False
    assert result["id_proposicao"] is None
    assert result["candidatos"] == []
    assert result["casa"] == "camara"


def test_resolve_proposition_http_error_tolerance():
    """T019: Valida tolerância graciosa em caso de HTTP 500 do servidor da API."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client = LegislativeClient(transport=httpx.MockTransport(handler))
    result = resolve_proposition(
        casa="camara",
        termo_busca="termo com erro",
        client=client,
    )

    assert result["ambiguous"] is False
    assert result["id_proposicao"] is None
    assert result["candidatos"] == []
    assert result["casa"] == "camara"


def test_resolve_proposition_performance_and_cache():
    """T024: Valida latência de resolução com cache em memória (<5ms por chamada)."""
    import time

    payload = {
        "dados": [
            {
                "id": 2253965,
                "siglaTipo": "PL",
                "numero": 2630,
                "ano": 2020,
                "ementa": "Lei das Fake News",
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = LegislativeClient(transport=httpx.MockTransport(handler))

    # Aquecimento de cache (1ª chamada)
    res_first = resolve_proposition(
        casa="camara",
        sigla_tipo="PL",
        numero=2630,
        ano=2020,
        client=client,
    )
    assert res_first["id_proposicao"] == 2253965

    # Execução de 200 consultas subsequentes no cache de sessão
    start = time.perf_counter()
    for _ in range(200):
        res = resolve_proposition(
            casa="camara",
            sigla_tipo="PL",
            numero=2630,
            ano=2020,
            client=client,
        )
        assert res["id_proposicao"] == 2253965
    elapsed = time.perf_counter() - start

    # Latência média por chamada deve ser < 1ms (< 0.001s)
    avg_latency = elapsed / 200
    assert avg_latency < 0.005, f"Latência média de {avg_latency*1000:.2f}ms excede limite de 5ms"





# --------------------------------------------------------------------------- #
# Tarefa 3.8: termos populares citam a sigla e preferem a proposição principal
# --------------------------------------------------------------------------- #

_EMENTA_REFORMA = "Altera o Sistema Tributário Nacional e institui a reforma tributária sobre o consumo."


def _client_with(items):
    return LegislativeClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"dados": items}))
    )


def _item(id_, sigla, numero, ano, ementa):
    return {"id": id_, "siglaTipo": sigla, "numero": numero, "ano": ano, "ementa": ementa}


def test_popular_term_with_sigla_filters_out_requerimentos():
    client = _client_with([
        _item(1, "REQ", 100, 2023, "Requer a reforma tributária em regime de urgência."),
        _item(2, "REQ", 101, 2023, "Requer audiência sobre a reforma tributária."),
        _item(45, "PEC", 45, 2019, _EMENTA_REFORMA),
    ])

    result = resolve_proposition(casa="camara", termo_busca="PEC da Reforma Tributária", client=client)

    assert result["ambiguous"] is False
    assert result["id_proposicao"] == 45
    assert result["sigla_tipo"] == "PEC"


def test_term_citing_sigla_without_matching_item_is_not_found():
    client = _client_with([
        _item(1, "REQ", 100, 2023, "Requer a reforma tributária em regime de urgência."),
        _item(7, "PL", 7, 2023, _EMENTA_REFORMA),
    ])

    result = resolve_proposition(casa="camara", termo_busca="PEC da Reforma Tributária", client=client)

    assert result["id_proposicao"] is None
    assert result["ambiguous"] is False


def test_term_without_sigla_prefers_main_proposition_over_requerimento():
    client = _client_with([
        _item(1, "REQ", 100, 2023, _EMENTA_REFORMA),
        _item(45, "PEC", 45, 2019, _EMENTA_REFORMA),
    ])

    result = resolve_proposition(casa="camara", termo_busca="reforma tributária", client=client)

    assert result["id_proposicao"] == 45


def test_term_keeps_requerimentos_when_they_are_the_only_matches():
    client = _client_with([_item(1, "REQ", 100, 2023, _EMENTA_REFORMA)])

    result = resolve_proposition(casa="camara", termo_busca="reforma tributária", client=client)

    assert result["id_proposicao"] == 1


def test_explicit_requerimento_term_is_not_filtered_out():
    client = _client_with([
        _item(1, "REQ", 100, 2023, _EMENTA_REFORMA),
        _item(45, "PEC", 45, 2019, _EMENTA_REFORMA),
    ])

    result = resolve_proposition(casa="camara", termo_busca="REQ reforma tributária", client=client)

    assert result["id_proposicao"] == 1


# --------------------------------------------------------------------------- #
# Relevância: o termo de busca precisa aparecer na ementa (sem falso positivo)
# --------------------------------------------------------------------------- #


def test_lone_candidate_that_misses_a_content_term_is_not_accepted():
    """Regressão da claim 5: a PEC 9/2023 (fundo partidário) não é a 'Reforma Tributária'."""
    client = _client_with([
        _item(
            164727, "PEC", 9, 2023,
            "Impõe aos partidos políticos a obrigatoriedade da aplicação de recursos financeiros para as "
            "candidaturas de pessoas pretas e pardas e reforça a imunidade tributária dos partidos políticos "
            "conforme previsto na Constituição Federal.",
        ),
    ])

    result = resolve_proposition(casa="camara", termo_busca="PEC da Reforma Tributária", client=client)

    assert result["id_proposicao"] is None
    assert result["ambiguous"] is False


def test_term_matches_when_every_content_term_is_in_the_ementa_even_with_stopwords_around():
    client = _client_with([_item(45, "PEC", 45, 2019, _EMENTA_REFORMA)])

    result = resolve_proposition(casa="camara", termo_busca="PEC da Reforma Tributária", client=client)

    assert result["id_proposicao"] == 45


def test_accents_and_case_do_not_hide_a_content_term():
    client = _client_with([_item(45, "PEC", 45, 2019, "ALTERA O SISTEMA TRIBUTÁRIO E INSTITUI A REFORMA TRIBUTÁRIA.")])

    result = resolve_proposition(casa="camara", termo_busca="reforma tributaria", client=client)

    assert result["id_proposicao"] == 45
