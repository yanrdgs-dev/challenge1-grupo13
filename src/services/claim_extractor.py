"""Módulo de extração de alegações factuais (claims) a partir de textos jornalísticos.

Atende aos critérios da Task 4.6:
- Extração estruturada de alegações centrais a partir de notícias e posts.
- Suporte a cliente LLM com fallback heurístico para garantia de estabilidade e ausência de timeouts.
"""

import re
import logging
from typing import Any, List, Optional

logger = logging.getLogger("Services.ClaimExtractor")


class ClaimExtractor:
    """Extrator de alegações com suporte a LLM e fallback heurístico determinístico."""

    def __init__(self, llm_client: Optional[Any] = None):
        """Inicializa o extrator de claims.

        Args:
            llm_client: Cliente de inferência LLM opcional (ex: src.core.llm_client.LLMClient).
        """
        self.llm_client = llm_client

    async def extract_claims(self, text: str) -> List[str]:
        """Extrai as alegações centrais presentes em um texto de notícia ou publicação.

        Args:
            text: Texto do artigo ou post a ser analisado.

        Returns:
            Lista de strings representando as alegações centrais extraídas.
        """
        if not text or not isinstance(text, str) or not text.strip():
            return []

        clean_text = text.strip()

        # 1. Se cliente LLM estiver injetado e ativo, tenta via inferência estruturada
        if self.llm_client is not None:
            try:
                claims = await self._extract_via_llm(clean_text)
                if claims:
                    return claims
            except Exception as err:
                logger.warning(f"Falha na extração via LLM, aplicando fallback: {err}")

        # 2. Extração heurística / determinística
        return self._extract_heuristic(clean_text)

    async def _extract_via_llm(self, text: str) -> List[str]:
        """Extrai alegações usando o cliente LLM."""
        prompt = (
            "Extraia as principais alegações factuais (afirmações verificáveis) do texto abaixo.\n"
            "Retorne apenas as alegações, uma por linha.\n\n"
            f"Texto: {text}\n\nAlegações:"
        )
        response = await self.llm_client.acomplete(prompt)
        lines = [line.strip("- *").strip() for line in response.splitlines() if line.strip()]
        return [l for l in lines if len(l) > 10]

    def _extract_heuristic(self, text: str) -> List[str]:
        """Extrai alegações de forma determinística dividindo em orações declarativas."""
        # Divide em sentenças
        sentences = re.split(r"(?<=[.!?])\s+", text)
        claims = [s.strip() for s in sentences if len(s.strip()) > 15]

        if not claims:
            claims = [text[:150].strip()]

        return claims
