"""Cliente HTTP especializado para consumo das APIs de Dados Abertos da Câmara e do Senado.

Atende ao Princípio VIII da Constituição (timeout estrito de 5s, cache em memória e tolerância a falhas).
"""

import logging
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

CAMARA_PROPOSICOES_URL = "https://dadosabertos.camara.leg.br/api/v2/proposicoes"
SENADO_MATERIAS_URL = "https://legis.senado.leg.br/dadosabertos/materia/pesquisa/lista"


class LegislativeClient:
    """Cliente HTTP com timeout padrão de 5.0 segundos e cache de sessão em memória."""

    def __init__(
        self,
        timeout: float = 5.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.timeout = timeout
        self.transport = transport
        self._client = httpx.Client(timeout=self.timeout, transport=self.transport)
        self._cache: Dict[str, Any] = {}

    def _make_cache_key(self, url: str, params: Optional[Dict[str, Any]] = None) -> str:
        """Gera chave estável de cache em memória."""
        if not params:
            return url
        sorted_items = sorted((str(k), str(v)) for k, v in params.items() if v is not None)
        return f"{url}?{'&'.join(f'{k}={v}' for k, v in sorted_items)}"

    def clear_cache(self) -> None:
        """Limpa o cache de sessão em memória."""
        self._cache.clear()

    def search_camara(
        self,
        sigla_tipo: Optional[str] = None,
        numero: Optional[int] = None,
        ano: Optional[int] = None,
        keywords: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Consulta proposições na API da Câmara dos Deputados.

        Args:
            sigla_tipo: Sigla da matéria (ex: 'PL', 'PEC').
            numero: Número da matéria.
            ano: Ano de apresentação.
            keywords: Termo textual ou tema para busca na ementa/palavras-chave.

        Returns:
            Lista de matérias retornadas pela API da Câmara.
        """
        params: Dict[str, Any] = {"ordem": "DESC", "ordenarPor": "id"}
        if sigla_tipo:
            params["siglaTipo"] = sigla_tipo
        if numero is not None:
            params["numero"] = numero
        if ano is not None:
            params["ano"] = ano
        if keywords:
            params["keywords"] = keywords

        cache_key = self._make_cache_key(CAMARA_PROPOSICOES_URL, params)
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            response = self._client.get(CAMARA_PROPOSICOES_URL, params=params)
            if response.status_code == 404:
                self._cache[cache_key] = []
                return []
            response.raise_for_status()
            data = response.json()
            items = data.get("dados", [])
            self._cache[cache_key] = items
            return items
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.warning("Falha na consulta à API da Câmara: %s", exc)
            return []

    def search_senado(
        self,
        sigla: Optional[str] = None,
        numero: Optional[int] = None,
        ano: Optional[int] = None,
        palavra: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Consulta matérias na API do Senado Federal.

        Args:
            sigla: Sigla da matéria (ex: 'PEC', 'PL').
            numero: Número da matéria.
            ano: Ano da matéria.
            palavra: Termo textual para pesquisa no Senado.

        Returns:
            Lista padronizada de matérias retornadas pelo Senado.
        """
        params: Dict[str, Any] = {}
        if sigla:
            params["sigla"] = sigla
        if numero is not None:
            params["numero"] = numero
        if ano is not None:
            params["ano"] = ano
        if palavra:
            params["palavra"] = palavra

        cache_key = self._make_cache_key(SENADO_MATERIAS_URL, params)
        if cache_key in self._cache:
            return self._cache[cache_key]

        headers = {"Accept": "application/json"}
        try:
            response = self._client.get(SENADO_MATERIAS_URL, params=params, headers=headers)
            if response.status_code == 404:
                self._cache[cache_key] = []
                return []
            response.raise_for_status()
            data = response.json()

            # Normalização da estrutura aninhada do Senado
            materias_raw = (
                data.get("PesquisaBasicaMateria", {})
                .get("Materias", {})
                .get("Materia", [])
            )
            if isinstance(materias_raw, dict):
                materias_raw = [materias_raw]

            normalized_list: List[Dict[str, Any]] = []
            for item in materias_raw:
                cod = item.get("Codigo") or item.get("IdentificacaoProcesso") or item.get("id")
                try:
                    cod_int = int(cod) if cod is not None else None
                except (ValueError, TypeError):
                    cod_int = None

                num_raw = item.get("Numero") or item.get("numero")
                try:
                    num_int = int(num_raw) if num_raw is not None else None
                except (ValueError, TypeError):
                    num_int = None

                ano_raw = item.get("Ano") or item.get("ano")
                try:
                    ano_int = int(ano_raw) if ano_raw is not None else None
                except (ValueError, TypeError):
                    ano_int = None

                normalized_list.append(
                    {
                        "id": cod_int,
                        "sigla": item.get("Sigla") or item.get("sigla") or sigla,
                        "siglaTipo": item.get("Sigla") or item.get("sigla") or sigla,
                        "numero": num_int,
                        "ano": ano_int,
                        "ementa": item.get("Ementa") or item.get("ementa") or item.get("DescricaoObjetivo", ""),
                    }
                )

            self._cache[cache_key] = normalized_list
            return normalized_list
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.warning("Falha na consulta à API do Senado: %s", exc)
            return []

    def close(self) -> None:
        """Fecha a sessão HTTP subjacente."""
        self._client.close()

    def __enter__(self) -> "LegislativeClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
