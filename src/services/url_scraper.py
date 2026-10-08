"""Módulo de scraping e extração limpa de artigos jornalísticos via trafilatura.

Atende aos critérios da Task 4.1 (Issue #23):
- Extração limpa do corpo editorial de notícias fornecidas via URL.
- Remoção de menus de navegação, scripts e rodapés.
- Coleta de metadados: título, autor e data de publicação.
- Tratamento de exceções específicas para URLs inválidas, falhas de DNS e códigos HTTP.
- Sinalização amigável de restrição por paywall ou ausência de texto legível.
"""

import logging
import urllib.parse
from typing import Any, Dict, Optional

import requests
import trafilatura
from bs4 import BeautifulSoup

logger = logging.getLogger("Services.UrlScraper")


def is_valid_url(url: str) -> bool:
    """Verifica se a string fornecida representa uma URL HTTP/HTTPS válida.

    Args:
        url: Endereço web a ser validado.

    Returns:
        True se a URL possui esquema HTTP/HTTPS e host definidos; False caso contrário.
    """
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
        return bool(parsed.scheme in ("http", "https") and parsed.netloc)
    except Exception:
        return False


def extract_article(url: str, timeout: int = 10) -> Dict[str, Any]:
    """Extrai metadados e corpo editorial limpo de um artigo jornalístico a partir de sua URL.

    Args:
        url: Link da notícia a ser raspada.
        timeout: Tempo limite de espera pela requisição HTTP em segundos (padrão: 10s).

    Returns:
        Dicionário estruturado com as seguintes chaves:
        - success (bool): Se a extração ocorreu com êxito.
        - error_type (Optional[str]): Código do erro ou None em caso de sucesso.
        - message (str): Mensagem descritiva do resultado da operação.
        - title (Optional[str]): Título da matéria jornalística.
        - author (Optional[str]): Autor ou equipe editorial.
        - publish_date (Optional[str]): Data de publicação identificada.
        - clean_text (str): Corpo editorial limpo da notícia.
        - url (str): URL original fornecida.
    """
    clean_url = url.strip() if isinstance(url, str) else ""

    if not is_valid_url(clean_url):
        return {
            "success": False,
            "error_type": "INVALID_URL",
            "message": f"A URL '{url}' é inválida ou malformada.",
            "title": None,
            "author": None,
            "publish_date": None,
            "clean_text": "",
            "url": clean_url,
        }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    try:
        response = requests.get(clean_url, headers=headers, timeout=timeout)

        # 1. Tratamento específico de códigos de erro HTTP
        if response.status_code == 403:
            return {
                "success": False,
                "error_type": "PAYWALL_OR_FORBIDDEN",
                "message": "Acesso negado ou protegido por paywall/autenticação (HTTP 403).",
                "title": None,
                "author": None,
                "publish_date": None,
                "clean_text": "",
                "url": clean_url,
            }
        elif response.status_code == 404:
            return {
                "success": False,
                "error_type": "NOT_FOUND",
                "message": "Página da notícia não encontrada (HTTP 404).",
                "title": None,
                "author": None,
                "publish_date": None,
                "clean_text": "",
                "url": clean_url,
            }
        elif response.status_code >= 400:
            return {
                "success": False,
                "error_type": "HTTP_ERROR",
                "message": f"Erro HTTP ao acessar notícia: status {response.status_code}.",
                "title": None,
                "author": None,
                "publish_date": None,
                "clean_text": "",
                "url": clean_url,
            }

        html = response.text

        # 2. Extração de metadados via trafilatura (com fallback via BeautifulSoup)
        meta = trafilatura.extract_metadata(html)
        title: Optional[str] = meta.title if meta and meta.title else None
        author: Optional[str] = meta.author if meta and meta.author else None
        publish_date: Optional[str] = meta.date if meta and meta.date else None

        if not title:
            try:
                soup = BeautifulSoup(html, "html.parser")
                title_tag = soup.find("title") or soup.find("h1")
                if title_tag:
                    title = title_tag.get_text(strip=True)
            except Exception:
                pass

        # 3. Extração do corpo textual limpo
        clean_text = trafilatura.extract(
            html,
            url=clean_url,
            include_links=False,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        ) or ""

        # 4. Detecção de conteúdo vazio ou bloqueio por JavaScript/paywall
        if not clean_text or len(clean_text.strip()) < 50:
            return {
                "success": False,
                "error_type": "EMPTY_CONTENT",
                "message": (
                    "Não foi possível extrair o texto editorial da matéria "
                    "(conteúdo protegido por paywall, login ou renderização exclusiva via JavaScript)."
                ),
                "title": title,
                "author": author,
                "publish_date": publish_date,
                "clean_text": "",
                "url": clean_url,
            }

        return {
            "success": True,
            "error_type": None,
            "message": "Artigo extraído com sucesso.",
            "title": title,
            "author": author,
            "publish_date": publish_date,
            "clean_text": clean_text.strip(),
            "url": clean_url,
        }

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as net_err:
        logger.warning("Falha de rede ou timeout ao acessar URL '%s': %s", clean_url, net_err)
        return {
            "success": False,
            "error_type": "NETWORK_ERROR",
            "message": f"Falha de conexão ou timeout ao tentar acessar o servidor: {net_err}",
            "title": None,
            "author": None,
            "publish_date": None,
            "clean_text": "",
            "url": clean_url,
        }
    except Exception as exc:
        logger.error("Erro inesperado ao raspar artigo em '%s': %s", clean_url, exc, exc_info=True)
        return {
            "success": False,
            "error_type": "UNKNOWN_ERROR",
            "message": f"Erro inesperado durante a extração do artigo: {exc}",
            "title": None,
            "author": None,
            "publish_date": None,
            "clean_text": "",
            "url": clean_url,
        }
