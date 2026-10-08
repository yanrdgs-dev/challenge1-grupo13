"""Testes unitários para os extratores de dados abertos (src.ingestion.extractors).

Garante cobertura de testes sem chamadas de rede externas (100% mockado via unittest.mock),
atendendo às regras de TDD e isolamento do AGENTS.md.
"""

from unittest.mock import MagicMock, patch
from src.ingestion.extractors import (
    scrape_dados_abertos_camara,
    scrape_dados_abertos_senado,
    scrape_dados_abertos_tse,
)


def test_scrape_dados_abertos_camara_sucesso():
    """Valida extração bem-sucedida de proposições da Câmara dos Deputados."""
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
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_payload

    with patch("requests.get", return_value=mock_response) as mock_get:
        resultado = scrape_dados_abertos_camara(limit=5)

        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert kwargs["params"]["itens"] == 5
        assert len(resultado) == 1
        assert resultado[0]["id_fonte"] == "CAMARA_2253965"
        assert resultado[0]["casa"] == "Camara dos Deputados"
        assert resultado[0]["tipo"] == "PL"
        assert resultado[0]["numero"] == 2630
        assert resultado[0]["ano"] == 2020
        assert resultado[0]["texto_ementa"] == "Institui a Lei Brasileira de Liberdade, Responsabilidade e Transparência na Internet."
        assert "2253965" in resultado[0]["url"]


def test_scrape_dados_abertos_camara_erro_http():
    """Valida retorno de lista vazia quando a API da Câmara retorna erro HTTP."""
    mock_response = MagicMock()
    mock_response.status_code = 500

    with patch("requests.get", return_value=mock_response):
        resultado = scrape_dados_abertos_camara()
        assert resultado == []


def test_scrape_dados_abertos_senado_sucesso():
    """Valida extração bem-sucedida de matérias do Senado Federal."""
    mock_payload = {
        "ListaMateriasAtualizadas": {
            "Materias": {
                "Materia": [
                    {
                        "IdentificacaoMateria": {
                            "CodigoMateria": "137350",
                            "SiglaSubtipoMateria": "PEC",
                            "NumeroMateria": "45",
                            "AnoMateria": "2019",
                        },
                        "EmentaMateria": "Altera o Sistema Tributário Nacional.",
                    }
                ]
            }
        }
    }
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_payload

    with patch("requests.get", return_value=mock_response) as mock_get:
        resultado = scrape_dados_abertos_senado(limit=2)

        mock_get.assert_called_once()
        assert len(resultado) == 1
        assert resultado[0]["id_fonte"] == "SENADO_137350"
        assert resultado[0]["casa"] == "Senado Federal"
        assert resultado[0]["tipo"] == "PEC"
        assert resultado[0]["numero"] == "45"
        assert resultado[0]["ano"] == "2019"
        assert resultado[0]["texto_ementa"] == "Altera o Sistema Tributário Nacional."
        assert "137350" in resultado[0]["url"]


def test_scrape_dados_abertos_senado_excecao():
    """Valida retorno de lista vazia caso ocorra erro no payload ou na resposta do Senado."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("JSON inválido")

    with patch("requests.get", return_value=mock_response):
        resultado = scrape_dados_abertos_senado()
        assert resultado == []


def test_scrape_dados_abertos_tse_sucesso():
    """Valida scraping da página do portal de dados abertos do TSE."""
    html_content = """
    <html>
        <body>
            <li class="dataset-item">
                <h2 class="dataset-heading">
                    <a href="/dataset/candidatos-2024">Candidatos - 2024</a>
                </h2>
            </li>
            <li class="dataset-item">
                <h2 class="dataset-heading">
                    <a href="https://externo.com/dataset/bens-candidatos">Bens dos Candidatos</a>
                </h2>
            </li>
        </body>
    </html>
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html_content

    with patch("requests.get", return_value=mock_response) as mock_get:
        resultado = scrape_dados_abertos_tse()

        mock_get.assert_called_once()
        assert len(resultado) == 2
        assert resultado[0]["id_fonte"] == "TSE_1"
        assert resultado[0]["fonte"] == "TSE - Dados Abertos"
        assert resultado[0]["titulo_conjunto"] == "Candidatos - 2024"
        assert resultado[0]["url_conjunto"] == "https://dadosabertos.tse.jus.br/dataset/candidatos-2024"

        assert resultado[1]["id_fonte"] == "TSE_2"
        assert resultado[1]["titulo_conjunto"] == "Bens dos Candidatos"
        assert resultado[1]["url_conjunto"] == "https://externo.com/dataset/bens-candidatos"


def test_scrape_dados_abertos_tse_erro_requisicao():
    """Valida tratamento gracioso de falha na requisição ao TSE."""
    with patch("requests.get", side_effect=Exception("Erro de conexão")):
        resultado = scrape_dados_abertos_tse()
        assert resultado == []
