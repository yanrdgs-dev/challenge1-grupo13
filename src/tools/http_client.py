"""Cliente HTTP resiliente com suporte a retries, backoff exponencial, redirects e cache de sessão.

Atende aos requisitos de arquitetura da Parte 5 e da Constituição do projeto:
- Timeout configurável para evitar bloqueio em requisições lentas.
- Retry com backoff exponencial para falhas transitórias (5xx, timeouts de rede).
- Suporte nativo a redirecionamentos (follow_redirects=True), essencial para APIs do Senado.
- Cache em memória por sessão de claim para evitar refetches desnecessários.
"""

from typing import Any, Dict, Optional
import logging
import time
import httpx

logger = logging.getLogger(__name__)


class HttpNetworkError(Exception):
    """Exceção levantada quando requisições HTTP falham após esgotadas as tentativas."""
    pass


class HttpClient:
    """Cliente HTTP centralizado e resiliente para o agente de fact-checking."""

    def __init__(
        self,
        timeout: float = 8.0,
        max_retries: int = 3,
        retry_delay: float = 0.5,
        cache_enabled: bool = True,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.cache_enabled = cache_enabled
        self._cache: Dict[str, Any] = {}

        self.default_headers = {
            "Accept": "application/json",
            "User-Agent": "FactCheckingAgent-CBL-G13/1.0",
        }

        self._client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers=self.default_headers,
        )

    def _make_cache_key(self, url: str, params: Optional[Dict[str, Any]] = None) -> str:
        """Gera chave determinística para cacheamento em memória."""
        if not params:
            return url
        sorted_params = tuple(sorted((str(k), str(v)) for k, v in params.items()))
        return f"{url}?{sorted_params}"

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Executa requisição GET com retry exponencial, verificação de cache e decodificação JSON."""
        cache_key = self._make_cache_key(url, params)

        if self.cache_enabled and cache_key in self._cache:
            logger.debug("Cache hit para requisição: %s", cache_key)
            return self._cache[cache_key]

        last_exception: Optional[Exception] = None
        current_delay = self.retry_delay

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug("HTTP GET %s (tentativa %d/%d)", url, attempt, self.max_retries)
                response = self._client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                if self.cache_enabled:
                    self._cache[cache_key] = data

                return data

            except httpx.HTTPStatusError as exc:
                last_exception = exc
                status = exc.response.status_code
                logger.warning(
                    "HTTP Status %d na chamada para %s (tentativa %d/%d)",
                    status,
                    url,
                    attempt,
                    self.max_retries,
                )
                # Erros 4xx (exceto 429) geralmente não são transitórios
                if 400 <= status < 500 and status != 429:
                    raise HttpNetworkError(
                        f"Erro HTTP {status} ao consultar {url}: {exc.response.text}"
                    ) from exc

            except (httpx.TimeoutException, httpx.RequestError) as exc:
                last_exception = exc
                logger.warning(
                    "Erro de conexão/timeout em %s (tentativa %d/%d): %s",
                    url,
                    attempt,
                    self.max_retries,
                    exc,
                )

            if attempt < self.max_retries:
                time.sleep(current_delay)
                current_delay *= 2.0

        raise HttpNetworkError(
            f"Tentativas esgotadas ({self.max_retries}) ao consultar {url}. "
            f"Último erro: {last_exception}"
        ) from last_exception

    def clear_cache(self) -> None:
        """Limpa o cache em memória."""
        self._cache.clear()

    def close(self) -> None:
        """Fecha a sessão HTTP subjacente."""
        self._client.close()
