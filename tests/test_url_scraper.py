"""Testes unitários para o serviço de extração de artigos web (Task 4.1).

Atende estritamente às regras de TDD e isolamento do AGENTS.md,
utilizando unittest.mock para simular requisições HTTP e cenários de rede.
"""

from unittest.mock import MagicMock, patch
import requests
import pytest

from src.services.url_scraper import extract_article, is_valid_url


def test_is_valid_url():
    """Valida identificação de URLs válidas e inválidas."""
    assert is_valid_url("https://noticias.uol.com.br/politica/materia.htm") is True
    assert is_valid_url("http://g1.globo.com/politica/noticia.html") is True
    assert is_valid_url("") is False
    assert is_valid_url("invalido") is False
    assert is_valid_url("ftp://servidor.com/arquivo.txt") is False
    assert is_valid_url("https://") is False


def test_extract_article_sucesso():
    """Valida extração bem-sucedida de metadados e corpo editorial da notícia."""
    html = """
    <!DOCTYPE html>
    <html>
        <head>
            <title>Câmara aprova texto-base da nova reforma tributária</title>
            <meta name="author" content="Redação Política">
            <meta name="date" content="2026-10-08">
        </head>
        <body>
            <header>
                <nav><a href="/">Início</a> | <a href="/politica">Política</a></nav>
            </header>
            <article>
                <h1>Câmara aprova texto-base da nova reforma tributária</h1>
                <p>O plenário da Câmara dos Deputados aprovou na noite desta quarta-feira o texto-base da proposta de regulamentação da reforma tributária.</p>
                <p>O texto segue agora para apreciação e votação dos destaques pelos deputados em sessão extraordinária.</p>
            </article>
            <footer>
                <p>Todos os direitos reservados © 2026</p>
            </footer>
        </body>
    </html>
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html

    with patch("requests.get", return_value=mock_response):
        resultado = extract_article("https://noticias.exemplo.com/politica/reforma")

        assert resultado["success"] is True
        assert resultado["error_type"] is None
        assert resultado["title"] == "Câmara aprova texto-base da nova reforma tributária"
        assert resultado["author"] == "Redação Política"
        assert resultado["publish_date"] == "2026-10-08"
        assert "texto-base da proposta" in resultado["clean_text"]
        # Garante que rodapés ou menus de navegação não contaminaram o corpo limpo
        assert "Início | Política" not in resultado["clean_text"]


def test_extract_article_url_invalida():
    """Valida que URLs malformadas são rejeitadas antes de qualquer requisição."""
    with patch("requests.get") as mock_get:
        resultado = extract_article("url_malformada_sem_protocolo")

        mock_get.assert_not_called()
        assert resultado["success"] is False
        assert resultado["error_type"] == "INVALID_URL"
        assert resultado["clean_text"] == ""


def test_extract_article_http_403_paywall_ou_bloqueio():
    """Valida detecção amigável de erro HTTP 403 (Paywall ou Acesso Negado)."""
    mock_response = MagicMock()
    mock_response.status_code = 403

    with patch("requests.get", return_value=mock_response):
        resultado = extract_article("https://jornal.com/materia-fechada")

        assert resultado["success"] is False
        assert resultado["error_type"] == "PAYWALL_OR_FORBIDDEN"
        assert "paywall" in resultado["message"].lower() or "acesso negado" in resultado["message"].lower()
        assert resultado["clean_text"] == ""


def test_extract_article_http_404_nao_encontrado():
    """Valida tratamento de página não encontrada (HTTP 404)."""
    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch("requests.get", return_value=mock_response):
        resultado = extract_article("https://jornal.com/materia-inexistente")

        assert resultado["success"] is False
        assert resultado["error_type"] == "NOT_FOUND"
        assert resultado["clean_text"] == ""


def test_extract_article_http_500_erro_servidor():
    """Valida tratamento de erro interno do servidor de notícias (HTTP 500)."""
    mock_response = MagicMock()
    mock_response.status_code = 500

    with patch("requests.get", return_value=mock_response):
        resultado = extract_article("https://jornal.com/materia-com-erro-500")

        assert resultado["success"] is False
        assert resultado["error_type"] == "HTTP_ERROR"
        assert resultado["clean_text"] == ""


def test_extract_article_erro_dns_ou_conexao():
    """Valida tratamento de erro de conexão e resolução de DNS."""
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("Falha de DNS")):
        resultado = extract_article("https://dominio-que-nao-existe.com.br/artigo")

        assert resultado["success"] is False
        assert resultado["error_type"] == "NETWORK_ERROR"
        assert resultado["clean_text"] == ""


def test_extract_article_timeout():
    """Valida tratamento de timeout na requisição ao portal."""
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Tempo limite esgotado")):
        resultado = extract_article("https://site-lento.com/noticia")

        assert resultado["success"] is False
        assert resultado["error_type"] == "NETWORK_ERROR"
        assert resultado["clean_text"] == ""


def test_extract_article_conteudo_vazio_ou_bloqueio_js():
    """Valida retorno amigável caso o HTML retornado não contenha texto editorial extraível."""
    html_vazio = "<html><body><div id='app'>Assine agora para ler o conteúdo exclusivo.</div></body></html>"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html_vazio

    with patch("requests.get", return_value=mock_response):
        resultado = extract_article("https://site-com-paywall-js.com/noticia")

        assert resultado["success"] is False
        assert resultado["error_type"] == "EMPTY_CONTENT"
        assert resultado["clean_text"] == ""
