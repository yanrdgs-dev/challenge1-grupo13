"""Esquema de dados para alegações atômicas extraídas de textos jornalísticos."""

from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator


class AtomicClaim(BaseModel):
    """Representa uma afirmação factual, atômica e potencialmente verificável.

    Decompõe trechos complexos de notícias em unidades mínimas e autossuficientes
    de verificação factual contra bases de dados governamentais ou regras institucionais.
    """

    claim: str = Field(
        ...,
        description="Afirmação atômica, concreta e factualmente verificável.",
    )
    category: Optional[str] = Field(
        default=None,
        description="Categoria temática da alegação (ex: GASTOS, VOTACOES, PATRIMONIO, INSTITUCIONAL, OUTRO).",
    )
    target_entity: Optional[str] = Field(
        default=None,
        description="Entidade pública ou parlamentar mencionado na afirmação.",
    )
    context: Optional[str] = Field(
        default=None,
        description="Trecho original do texto jornalístico que originou a afirmação.",
    )
    verifiable: bool = Field(
        default=True,
        description="Indica se a afirmação possui parâmetros checáveis contra dados públicos.",
    )

    def __init__(self, claim_or_text: Optional[str] = None, **data: Any):
        if claim_or_text is not None and "claim" not in data:
            data["claim"] = claim_or_text
        super().__init__(**data)

    @model_validator(mode="before")
    @classmethod
    def _coerce_and_validate(cls, data: Any) -> Any:
        """Permite inicialização simplificada a partir de strings diretas ou chave alternativa 'text'."""
        if isinstance(data, str):
            return {"claim": data.strip()}
        if isinstance(data, dict):
            # Normalização de chave alternativa 'text'
            if "claim" not in data and "text" in data:
                data["claim"] = data["text"]
            elif "claim" in data and "text" not in data:
                data["text"] = data["claim"]
        return data

    @property
    def text(self) -> str:
        """Alias para o texto da alegação para maior interoperabilidade com pipelines NLP."""
        return self.claim

    def __getitem__(self, item: str) -> Any:
        """Permite acesso indexado padrão chave/valor (compatibilidade com dicionários)."""
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)
