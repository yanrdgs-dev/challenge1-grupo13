"""Suíte de testes unitários para as tools do Grupo 5: Votações (API ao vivo).

Seguindo estritamente as regras de TDD (Regras 7 e 8 da Constituição do projeto):
- Cobertura de caminho feliz para Câmara e Senado.
- Cobertura de resultados vazios / ausência de evento (id 28).
- Cobertura de quebra de votos / unanimidade (id 15).
- Cobertura de sessões conjuntas de veto (id 20).
- Cobertura de frequência / faltas em plenário (id 7).
- Tratamento de parâmetros inválidos.
- Simulação de timeout e erros de rede via mocks (sem chamadas reais em testes unitários).
- Validação de cache de sessão e retries do cliente HTTP.
"""

from unittest.mock import MagicMock, patch
import httpx
import pytest

from src.tools.http_client import HttpClient, HttpNetworkError
from src.tools.votacoes_api import (
    get_proposition_vote_result,
    get_proposition_vote_breakdown,
    get_congress_veto_sessions,
    get_plenary_attendance,
)


# ============================================================================
# 1. TESTES DO HTTP CLIENT (RETRY, BACKOFF, CACHE, TIMEOUT)
# ============================================================================


def test_http_client_get_json_success():
    """Valida requisição HTTP bem-sucedida retornando JSON decodificado."""
    client = HttpClient(cache_enabled=False)
    with patch.object(client._client, "get") as mock_get:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok", "dados": [1, 2, 3]}
        mock_get.return_value = mock_response

        res = client.get_json("https://dadosabertos.camara.leg.br/api/v2/test", params={"ano": 2023})
        assert res == {"status": "ok", "dados": [1, 2, 3]}
        mock_get.assert_called_once()


def test_http_client_session_cache():
    """Valida que chamadas idênticas reutilizam o cache em memória e não refazem o GET."""
    client = HttpClient(cache_enabled=True)
    with patch.object(client._client, "get") as mock_get:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"proposicao": "PL 2630"}
        mock_get.return_value = mock_response

        # Primeira chamada: busca via rede
        res1 = client.get_json("https://api.exemplo.gov.br/item/10")
        # Segunda chamada: deve vir do cache
        res2 = client.get_json("https://api.exemplo.gov.br/item/10")

        assert res1 == res2
        assert mock_get.call_count == 1


def test_http_client_retry_and_backoff_on_transient_error():
    """Valida retry com sucesso na segunda tentativa após erro 503."""
    client = HttpClient(max_retries=2, retry_delay=0.01)
    with patch.object(client._client, "get") as mock_get:
        err_response = MagicMock(spec=httpx.Response)
        err_response.status_code = 503
        err_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service Unavailable", request=MagicMock(), response=err_response
        )

        ok_response = MagicMock(spec=httpx.Response)
        ok_response.status_code = 200
        ok_response.json.return_value = {"success": True}

        mock_get.side_effect = [
            httpx.HTTPStatusError("Service Unavailable", request=MagicMock(), response=err_response),
            ok_response,
        ]

        data = client.get_json("https://api.exemplo.gov.br/recurso")
        assert data == {"success": True}
        assert mock_get.call_count == 2


def test_http_client_raises_network_error_when_retries_exhausted():
    """Valida lançamento de HttpNetworkError após esgotar tentativas em caso de Timeout."""
    client = HttpClient(max_retries=2, retry_delay=0.01)
    with patch.object(client._client, "get") as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Timeout na conexão")

        with pytest.raises(HttpNetworkError) as exc_info:
            client.get_json("https://api.exemplo.gov.br/timeout")

        assert "Timeout" in str(exc_info.value) or "esgotadas" in str(exc_info.value)
        assert mock_get.call_count == 2


# ============================================================================
# 2. TESTES DA TOOL 5.1: get_proposition_vote_result
# ============================================================================


def test_get_proposition_vote_result_camara_happy_path():
    """Valida consulta de votação na Câmara (PL 2630/2020 - Golden Dataset id 4)."""
    mock_camara_payload = {
        "dados": [
            {
                "id": "2310837-8",
                "data": "2023-04-25",
                "descricao": "Aprovado o Requerimento de Urgência (Art. 154 do RICD). Sim: 238; não: 192; total: 430.",
                "aprovacao": 1,
            },
            {
                "id": "2256735-128",
                "data": "2022-06-08",
                "descricao": "Deferida a retirada do REQ 878/2022 requerida nos termos do caput do art. 104.",
                "aprovacao": 1,
            },
        ]
    }

    with patch("src.tools.votacoes_api.http_client.get_json", return_value=mock_camara_payload):
        results = get_proposition_vote_result(id_proposicao="2256735", casa="camara")

        assert isinstance(results, list)
        assert len(results) == 2
        assert results[0] == {
            "id_votacao": "2310837-8",
            "data": "2023-04-25",
            "tipo_votacao": "Aprovado o Requerimento de Urgência (Art. 154 do RICD). Sim: 238; não: 192; total: 430.",
            "aprovado": True,
        }


def test_get_proposition_vote_result_with_filter():
    """Valida filtro por tipo_votacao (ex.: 'urgência')."""
    mock_camara_payload = {
        "dados": [
            {
                "id": "2310837-8",
                "data": "2023-04-25",
                "descricao": "Aprovado o Requerimento de Urgência.",
                "aprovacao": 1,
            },
            {
                "id": "2256735-128",
                "data": "2022-06-08",
                "descricao": "Parecer de mérito em comissão.",
                "aprovacao": 0,
            },
        ]
    }

    with patch("src.tools.votacoes_api.http_client.get_json", return_value=mock_camara_payload):
        filtered = get_proposition_vote_result(
            id_proposicao="2256735", casa="camara", tipo_votacao="urgência"
        )
        assert len(filtered) == 1
        assert filtered[0]["id_votacao"] == "2310837-8"
        assert filtered[0]["aprovado"] is True


def test_get_proposition_vote_result_empty_returns_empty_list():
    """Valida retorno de lista vazia para matéria ainda não votada (Golden Dataset id 28 - INCONCLUSIVO)."""
    with patch("src.tools.votacoes_api.http_client.get_json", return_value={"dados": []}):
        results = get_proposition_vote_result(id_proposicao="9999999", casa="camara")
        assert results == []


def test_get_proposition_vote_result_senado_happy_path():
    """Valida consulta de votações no Senado (PEC 45/2019 - Golden Dataset id 5)."""
    mock_senado_payload = {
        "VotacaoMateria": {
            "Materia": {
                "IdentificacaoMateria": {"CodigoMateria": "158930"},
                "Votacoes": {
                    "Votacao": [
                        {
                            "CodigoSessaoVotacao": "6773",
                            "SessaoPlenaria": {"DataSessao": "2023-11-08"},
                            "DescricaoVotacao": "Votação nominal em primeiro turno da PEC da Reforma Tributária (texto-base).",
                            "DescricaoResultado": "Aprovado",
                        }
                    ]
                },
            }
        }
    }

    with patch("src.tools.votacoes_api.http_client.get_json", return_value=mock_senado_payload):
        results = get_proposition_vote_result(
            id_proposicao="158930", casa="senado", tipo_votacao="texto-base"
        )
        assert len(results) == 1
        assert results[0] == {
            "id_votacao": "6773",
            "data": "2023-11-08",
            "tipo_votacao": "Votação nominal em primeiro turno da PEC da Reforma Tributária (texto-base).",
            "aprovado": True,
        }


def test_get_proposition_vote_result_invalid_casa():
    """Valida lançamento de ValueError para casa desconhecida."""
    with pytest.raises(ValueError) as exc:
        get_proposition_vote_result(id_proposicao="123", casa="stf")
    assert "Casa inválida" in str(exc.value)


# ============================================================================
# 3. TESTES DA TOOL 5.2: get_proposition_vote_breakdown
# ============================================================================


def test_get_proposition_vote_breakdown_camara_happy_path():
    """Valida distribuição de votos na Câmara (Marco Temporal PL 490/2007 - Golden Dataset id 15)."""
    mock_votes_payload = {
        "dados": [
            {"tipoVoto": "Sim"},
            {"tipoVoto": "Sim"},
            {"tipoVoto": "Sim"},
            {"tipoVoto": "Não"},
            {"tipoVoto": "Não"},
            {"tipoVoto": "Abstenção"},
            {"tipoVoto": "Obstrução"},
            {"tipoVoto": "Ausente"},
        ]
    }

    with patch("src.tools.votacoes_api.http_client.get_json", return_value=mock_votes_payload):
        breakdown = get_proposition_vote_breakdown(id_votacao="2358509-84", casa="camara")

        assert breakdown == {
            "sim": 3,
            "nao": 2,
            "abstencao": 1,
            "obstrucao": 1,
            "ausente": 1,
            "outros": 0,
            "outros_detalhe": {},
            "total": 8,
        }
        # Refuta a claim de que a votação foi "sem nenhum voto contra" (nao > 0)
        assert breakdown["nao"] > 0


def test_get_proposition_vote_breakdown_senado_happy_path():
    """Valida detalhamento de votos no Senado a partir dos dados de votação nominal."""
    mock_senado_materia = {
        "VotacaoMateria": {
            "Materia": {
                "Votacoes": {
                    "Votacao": [
                        {
                            "CodigoSessaoVotacao": "6773",
                            "Votos": {
                                "VotoParlamentar": [
                                    {"SiglaVoto": "Sim"},
                                    {"SiglaVoto": "Sim"},
                                    {"SiglaVoto": "Não"},
                                    {"SiglaVoto": "Abstenção"},
                                    {"SiglaVoto": "Não Votou"},
                                ]
                            },
                        }
                    ]
                }
            }
        }
    }

    with patch("src.tools.votacoes_api.http_client.get_json", return_value=mock_senado_materia):
        breakdown = get_proposition_vote_breakdown(id_votacao="158930_6773", casa="senado")

        assert breakdown == {
            "sim": 2,
            "nao": 1,
            "abstencao": 1,
            "obstrucao": 0,
            "ausente": 1,
            "outros": 0,
            "outros_detalhe": {},
            "total": 5,
        }


def test_get_proposition_vote_breakdown_empty_votes():
    """Valida comportamento para votação sem votos nominais registrados."""
    with patch("src.tools.votacoes_api.http_client.get_json", return_value={"dados": []}):
        breakdown = get_proposition_vote_breakdown(id_votacao="000-0", casa="camara")
        assert breakdown == {
            "sim": 0,
            "nao": 0,
            "abstencao": 0,
            "obstrucao": 0,
            "ausente": 0,
            "outros": 0,
            "outros_detalhe": {},
            "total": 0,
        }


# ============================================================================
# 4. TESTES DA TOOL 5.3: get_congress_veto_sessions
# ============================================================================


def test_get_congress_veto_sessions_list_by_year():
    """Valida listagem de vetos presidenciais de um ano (Golden Dataset id 20)."""
    mock_vetos_list = {
        "Vetos": {
            "Veto": [
                {
                    "Codigo": "15549",
                    "Materia": {
                        "Numero": "1",
                        "Ano": "2023",
                        "EmTramitacao": "Não",
                    },
                },
                {
                    "Codigo": "16269",
                    "Materia": {
                        "Numero": "49",
                        "Ano": "2023",
                        "EmTramitacao": "Não",
                    },
                },
            ]
        }
    }

    with patch("src.tools.votacoes_api.http_client.get_json", return_value=mock_vetos_list):
        sessions = get_congress_veto_sessions(ano=2023)

        assert isinstance(sessions, list)
        assert len(sessions) == 2
        assert sessions[0]["codigo_veto"] == "15549"
        assert sessions[0]["numero"] == "1"
        assert sessions[0]["ano"] == 2023
        assert sessions[0]["em_tramitacao"] is False


def test_get_congress_veto_sessions_with_codigo_veto_detailed():
    """Valida busca detalhada de veto com dispositivos e PDF do resultado nominal."""
    mock_veto_detail = {
        "ResultadoVetoItemCN": {
            "Veto": {
                "Codigo": "16269",
                "Materia": {
                    "Numero": "49",
                    "Ano": "2023",
                    "EmTramitacao": "Não",
                },
                "Dispositivos": {
                    "Dispositivo": [
                        {
                            "Descricao": "§ 1º do art. 31",
                            "Situacao": "Rejeitado",
                            "TipoVotacao": "Cédula",
                            "DataSessao": "2024-05-09",
                        }
                    ]
                },
                "PdfsResultadoVotacao": {
                    "PdfResultadoVotacao": [
                        {
                            "URL": "https://legis.senado.leg.br/siscon/api/portalcn/pdfResultadoNominal/455/16269",
                            "Descricao": "Resultado da cédula apurada na Sessão Conjunta em 09/05/2024",
                        }
                    ]
                },
            }
        }
    }

    with patch("src.tools.votacoes_api.http_client.get_json", return_value=mock_veto_detail):
        sessions = get_congress_veto_sessions(ano=2023, codigo_veto="16269")

        assert len(sessions) == 1
        item = sessions[0]
        assert item["codigo_veto"] == "16269"
        assert item["data_sessao_conjunta"] == "2024-05-09"
        assert len(item["dispositivos"]) == 1
        assert item["dispositivos"][0] == {
            "descricao": "§ 1º do art. 31",
            "situacao": "Rejeitado",
            "tipo_votacao": "Cédula",
        }
        assert "pdfResultadoNominal" in item["url_pdf_resultado"]


def test_get_congress_veto_sessions_empty():
    """Valida retorno vazio quando ano não possui vetos."""
    with patch("src.tools.votacoes_api.http_client.get_json", return_value={"Vetos": {}}):
        sessions = get_congress_veto_sessions(ano=1900)
        assert sessions == []


# ============================================================================
# 5. TESTES DA TOOL 5.4: get_plenary_attendance
# ============================================================================


def test_get_plenary_attendance_camara_with_id_evento_happy_path():
    """Valida cálculo de presenças e inferência de ausências na Câmara (Golden Dataset id 7)."""
    # 3 deputados presentes no evento 73216
    mock_presentes_payload = {
        "dados": [
            {"id": 101, "nome": "Deputado Alfa", "siglaUf": "SP", "siglaPartido": "PARTIDO A"},
            {"id": 102, "nome": "Deputado Beta", "siglaUf": "RJ", "siglaPartido": "PARTIDO B"},
        ]
    }
    # 3 deputados no total em exercício na legislatura
    mock_todos_deputados = {
        "dados": [
            {"id": 101, "nome": "Deputado Alfa", "siglaUf": "SP", "siglaPartido": "PARTIDO A"},
            {"id": 102, "nome": "Deputado Beta", "siglaUf": "RJ", "siglaPartido": "PARTIDO B"},
            {"id": 103, "nome": "Deputado Gama", "siglaUf": "MG", "siglaPartido": "PARTIDO C"},
        ]
    }

    def fake_get_json(url, params=None):
        if "eventos/73216/deputados" in url:
            return mock_presentes_payload
        if "/deputados" in url:
            return mock_todos_deputados
        return {}

    with patch("src.tools.votacoes_api.http_client.get_json", side_effect=fake_get_json):
        res = get_plenary_attendance(casa="camara", periodo="2024-06-05", id_evento="73216")

        assert res["id_evento"] == "73216"
        assert len(res["presentes"]) == 2
        assert res["presentes"][0]["nome"] == "Deputado Alfa"

        # Deputado 103 não compareceu: deve estar nos ausentes inferidos
        assert len(res["ausentes_inferidos"]) == 1
        assert res["ausentes_inferidos"][0] == {
            "id_deputado": "103",
            "nome": "Deputado Gama",
            "uf": "MG",
            "partido": "PARTIDO C",
        }


def test_get_plenary_attendance_camara_filter_parlamentar():
    """Valida filtro por parlamentar_id específico."""
    mock_presentes = {
        "dados": [
            {"id": 101, "nome": "Deputado Alfa", "siglaUf": "SP", "siglaPartido": "PARTIDO A"},
        ]
    }
    mock_todos = {
        "dados": [
            {"id": 101, "nome": "Deputado Alfa", "siglaUf": "SP", "siglaPartido": "PARTIDO A"},
            {"id": 102, "nome": "Deputado Beta", "siglaUf": "RJ", "siglaPartido": "PARTIDO B"},
        ]
    }

    def fake_get_json(url, params=None):
        if "deputados" in url and "eventos" in url:
            return mock_presentes
        return mock_todos

    with patch("src.tools.votacoes_api.http_client.get_json", side_effect=fake_get_json):
        # Deputado presente
        res_presente = get_plenary_attendance(
            casa="camara", periodo="2024-06-05", id_evento="73216", parlamentar_id="101"
        )
        assert len(res_presente["presentes"]) == 1
        assert len(res_presente["ausentes_inferidos"]) == 0

        # Deputado ausente
        res_ausente = get_plenary_attendance(
            casa="camara", periodo="2024-06-05", id_evento="73216", parlamentar_id="102"
        )
        assert len(res_ausente["presentes"]) == 0
        assert len(res_ausente["ausentes_inferidos"]) == 1
        assert res_ausente["ausentes_inferidos"][0]["id_deputado"] == "102"


def test_get_plenary_attendance_senado_limitation():
    """Valida registro e retorno limpo da limitação da API do Senado para presença fora de votação nominal."""
    res = get_plenary_attendance(casa="senado", periodo="2024-06-01:2024-06-30")
    assert res["id_evento"] is None
    assert res["presentes"] == []
    assert res["ausentes_inferidos"] == []
    assert "limitação" in res.get("observacao", "").lower() or "senado" in res.get("observacao", "").lower()


# ============================================================================
# FASE 0: CORREÇÕES DE VEREDITO (aprovado tri-estado, placar completo, ausência inferida)
# ============================================================================


def _camara_votacoes(*itens):
    return {"dados": [{"id": f"1-{i}", "data": "2024-01-01", "descricao": d, "aprovacao": a} for i, (d, a) in enumerate(itens)]}


@pytest.mark.parametrize(
    "descricao, aprovacao, esperado",
    [
        ("Aprovado o Requerimento.", 1, True),
        ("Rejeitado o Requerimento.", 0, False),
        # A API devolve aprovacao nulo em votações de destaque ("Mantido o texto"): indeterminado, não "rejeitado".
        ("Mantido o texto. Sim: 290; não: 142; total: 432.", None, None),
        # O texto da descrição não decide: só o campo oficial.
        ("Aprovado o texto-base.", None, None),
        ("Não aprovado o requerimento.", 0, False),
    ],
)
def test_camara_aprovado_follows_only_the_official_aprovacao_field(descricao, aprovacao, esperado):
    with patch("src.tools.votacoes_api.http_client.get_json", return_value=_camara_votacoes((descricao, aprovacao))):
        results = get_proposition_vote_result(id_proposicao="1", casa="camara")
    assert results[0]["aprovado"] is esperado


def test_camara_missing_aprovacao_key_is_indeterminate():
    payload = {"dados": [{"id": "1-0", "data": "2024-01-01", "descricao": "Aprovado."}]}
    with patch("src.tools.votacoes_api.http_client.get_json", return_value=payload):
        assert get_proposition_vote_result(id_proposicao="1", casa="camara")[0]["aprovado"] is None


def _senado_votacao(resultado):
    item = {
        "CodigoSessaoVotacao": "1",
        "SessaoPlenaria": {"DataSessao": "2024-01-01"},
        "DescricaoVotacao": "Votação.",
    }
    if resultado is not None:
        item["DescricaoResultado"] = resultado
    return {"VotacaoMateria": {"Materia": {"Votacoes": {"Votacao": [item]}}}}


@pytest.mark.parametrize(
    "resultado, esperado",
    [
        ("Aprovado", True),
        ("Aprovada", True),
        ("Rejeitado", False),
        ("Rejeitada", False),
        # "Não aprovado" contém "aprovad": a heurística antiga lia isso como aprovação.
        ("Não aprovado", False),
        ("Não Aprovada", False),
        ("Prejudicado", None),
        ("", None),
        (None, None),
    ],
)
def test_senado_aprovado_reads_the_result_without_substring_traps(resultado, esperado):
    with patch("src.tools.votacoes_api.http_client.get_json", return_value=_senado_votacao(resultado)):
        results = get_proposition_vote_result(id_proposicao="1", casa="senado")
    assert results[0]["aprovado"] is esperado


def test_breakdown_camara_counts_unrecognised_vote_types_as_outros():
    """A Câmara registra o voto do presidente como 'Artigo 17': não pode sumir da contagem."""
    payload = {"dados": [{"tipoVoto": "Sim"}, {"tipoVoto": "Não"}, {"tipoVoto": "Artigo 17"}]}
    with patch("src.tools.votacoes_api.http_client.get_json", return_value=payload):
        placar = get_proposition_vote_breakdown(id_votacao="1-1", casa="camara")
    assert placar["outros"] == 1
    assert placar["outros_detalhe"] == {"Artigo 17": 1}
    assert placar["total"] == 3


def test_breakdown_senado_keeps_ap_pnrv_and_presidente_instead_of_dropping_them():
    """Votação 6773 real: Sim 53, Não 24, AP 3, Presidente 1 = 81. Antes, 4 votos sumiam."""
    votos = (
        [{"SiglaVoto": "Sim"}] * 53
        + [{"SiglaVoto": "Não"}] * 24
        + [{"SiglaVoto": "AP"}] * 3
        + [{"SiglaVoto": "P-NRV"}] * 2
        + [{"SiglaVoto": "Presidente (art. 51 RISF)"}]
    )
    payload = {"VotacaoMateria": {"Materia": {"Votacoes": {"Votacao": [{"CodigoSessaoVotacao": "6773", "Votos": {"VotoParlamentar": votos}}]}}}}
    with patch("src.tools.votacoes_api.http_client.get_json", return_value=payload):
        placar = get_proposition_vote_breakdown(id_votacao="158930_6773", casa="senado")
    assert (placar["sim"], placar["nao"]) == (53, 24)
    assert placar["outros"] == 6
    assert placar["outros_detalhe"] == {"AP": 3, "P-NRV": 2, "Presidente (art. 51 RISF)": 1}
    assert placar["total"] == 83


@pytest.mark.parametrize("casa", ["camara", "senado"])
def test_breakdown_options_always_add_up_to_total(casa):
    if casa == "camara":
        payload = {"dados": [{"tipoVoto": t} for t in ("Sim", "Não", "Abstenção", "Obstrução", "Ausente", "Artigo 17", "Sim")]}
    else:
        votos = [{"SiglaVoto": t} for t in ("Sim", "Não", "Abstenção", "Obstrução", "Não Votou", "AP", "NCom")]
        payload = {"VotacaoMateria": {"Materia": {"Votacoes": {"Votacao": [{"CodigoSessaoVotacao": "9", "Votos": {"VotoParlamentar": votos}}]}}}}
    with patch("src.tools.votacoes_api.http_client.get_json", return_value=payload):
        placar = get_proposition_vote_breakdown(id_votacao="1_9" if casa == "senado" else "1-9", casa=casa)
    soma = sum(placar[k] for k in ("sim", "nao", "abstencao", "obstrucao", "ausente", "outros"))
    assert soma == placar["total"]


def test_attendance_camara_states_that_absences_are_inferred():
    """Ausência é diferença contra o quadro atual de deputados, não um registro oficial de falta."""
    presentes = {"dados": [{"id": 101, "nome": "A", "siglaUf": "SP", "siglaPartido": "X"}]}
    todos = {"dados": [{"id": 101, "nome": "A", "siglaUf": "SP", "siglaPartido": "X"}, {"id": 102, "nome": "B", "siglaUf": "RJ", "siglaPartido": "Y"}]}

    def fake_get_json(url, params=None):
        return presentes if "eventos/73216/deputados" in url else todos

    with patch("src.tools.votacoes_api.http_client.get_json", side_effect=fake_get_json):
        res = get_plenary_attendance(casa="camara", periodo="2024-06-05", id_evento="73216")
    obs = res["observacao"].lower()
    assert "inferid" in obs and "suplente" in obs and "licenci" in obs
    assert "data da consulta" in obs, "o quadro é o de hoje, não o da data da sessão"
