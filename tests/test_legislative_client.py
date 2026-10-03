"""Testes unitários para o LegislativeClient (T004).

Cumpre o Princípio VII (TDD) e Princípio VIII (isolamento 100% offline via mocks,
simulação de timeout de 5s, erros 404/500 e cache de sessão).
"""

import httpx
import pytest

from src.tools.legislative_client import LegislativeClient


def test_legislative_client_default_timeout():
    """Valida se o timeout padrão do cliente é estritamente 5.0 segundos."""
    client = LegislativeClient()
    assert client.timeout == 5.0


def test_legislative_client_camara_mock_exact():
    """Valida busca na API da Câmara com retorno bem-sucedido."""
    mock_payload = {
        "dados": [
            {
                "id": 2253965,
                "siglaTipo": "PL",
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
        return httpx.Response(200, json=mock_payload)

    client = LegislativeClient(transport=httpx.MockTransport(handler))
    results = client.search_camara(sigla_tipo="PL", numero=2630, ano=2020)

    assert len(results) == 1
    assert results[0]["id"] == 2253965
    assert results[0]["siglaTipo"] == "PL"


def test_legislative_client_senado_mock_exact():
    """Valida busca na API do Senado com retorno bem-sucedido."""
    mock_payload = {
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
                        "Ementa": "Altera o Sistema Tributário Nacional.",
                    }
                ]
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "legis.senado.leg.br" in request.url.host
        assert request.headers.get("Accept") == "application/json"
        assert request.url.params.get("sigla") == "PEC"
        assert request.url.params.get("numero") == "45"
        assert request.url.params.get("ano") == "2019"
        return httpx.Response(200, json=mock_payload)

    client = LegislativeClient(transport=httpx.MockTransport(handler))
    results = client.search_senado(sigla="PEC", numero=45, ano=2019)

    assert len(results) == 1
    assert results[0]["id"] == 137350
    assert results[0]["sigla"] == "PEC"
    assert results[0]["numero"] == 45


def test_legislative_client_in_memory_session_cache():
    """Valida se consultas idênticas utilizam cache de sessão em memória sem requisições adicionais."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"dados": [{"id": 100, "siglaTipo": "PL", "numero": 1, "ano": 2024, "ementa": "Teste"}]})

    client = LegislativeClient(transport=httpx.MockTransport(handler))

    # 1ª chamada -> consome a rede mockada
    res1 = client.search_camara(sigla_tipo="PL", numero=1, ano=2024)
    assert call_count == 1
    assert len(res1) == 1

    # 2ª chamada idêntica -> consome cache em memória
    res2 = client.search_camara(sigla_tipo="PL", numero=1, ano=2024)
    assert call_count == 1  # Não deve incrementar
    assert res1 == res2

    # Limpar cache e chamar novamente -> chama mock novamente
    client.clear_cache()
    res3 = client.search_camara(sigla_tipo="PL", numero=1, ano=2024)
    assert call_count == 2
    assert res1 == res3


def test_legislative_client_timeout_handling():
    """Valida degradação graciosa em caso de Timeout (httpx.ConnectTimeout/ReadTimeout)."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Connection timed out after 5s")

    client = LegislativeClient(transport=httpx.MockTransport(handler))
    results = client.search_camara(sigla_tipo="PL", numero=999, ano=2024)

    # Não deve lançar exceção não tratada; deve retornar lista vazia de forma segura
    assert results == []


def test_legislative_client_http_500_handling():
    """Valida degradação graciosa quando a API retorna erro 500 do servidor."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client = LegislativeClient(transport=httpx.MockTransport(handler))
    results = client.search_senado(palavra="erro")

    assert results == []


def test_legislative_client_http_404_handling():
    """Valida retorno seguro quando a API retorna 404 Not Found."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    client = LegislativeClient(transport=httpx.MockTransport(handler))
    results = client.search_camara(keywords="inexistente")

    assert results == []
