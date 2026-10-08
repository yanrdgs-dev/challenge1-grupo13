"""Contratos e interfaces Pydantic para ferramentas do agente orquestrador (Task 2.3).

Define esquemas estritos de entrada e saída para todas as ferramentas
consumidas pelo fluxo de fact-checking político.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Funções Auxiliares de Validação de Strings
# ---------------------------------------------------------------------------

def _validate_non_empty_str(value: Any, field_name: str) -> str:
    """Valida e higieniza strings obrigatórias, impedindo valores em branco."""
    if value is None:
        raise ValueError(f"O campo '{field_name}' é obrigatório e não pode ser nulo.")

    if not isinstance(value, str):
        raise ValueError(f"O campo '{field_name}' deve ser do tipo string.")

    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"O campo '{field_name}' não pode ser vazio ou conter apenas espaços.")

    return cleaned


# ---------------------------------------------------------------------------
# Modelos de Entrada (Tool Inputs)
# ---------------------------------------------------------------------------

class TSEExpensesInput(BaseModel):
    """Parâmetros de consulta para prestação de contas de campanha eleitoral (TSE)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    politician_name: str = Field(
        ...,
        description="Nome civil, nome de urna ou apelido do candidato a ser consultado.",
    )
    year: int = Field(
        ...,
        description="Ano do pleito eleitoral (ex: 2022, 2024, 2026).",
    )
    state: Optional[str] = Field(
        default=None,
        description="Sigla da Unidade Federativa da candidatura (ex: 'SP', 'RS', 'BR').",
    )

    @field_validator("politician_name")
    @classmethod
    def validate_politician_name(cls, v: str) -> str:
        return _validate_non_empty_str(v, "politician_name")

    @field_validator("year")
    @classmethod
    def validate_year(cls, v: int) -> int:
        if not (1889 <= v <= 2100):
            raise ValueError(f"Ano eleitoral inválido ({v}). Deve estar entre 1889 e 2100.")
        return v

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip().upper()
        if not cleaned:
            return None
        return cleaned


class CamaraVoteInput(BaseModel):
    """Parâmetros de consulta para histórico de votação nominal de deputado na Câmara."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    politician_name: str = Field(
        ...,
        description="Nome parlamentar ou civil do deputado a consultar.",
    )
    bill_id: str = Field(
        ...,
        description="Identificador formal da proposição ou matéria legislativa (ex: 'PL 2630/2020').",
    )

    @field_validator("politician_name")
    @classmethod
    def validate_politician_name(cls, v: str) -> str:
        return _validate_non_empty_str(v, "politician_name")

    @field_validator("bill_id")
    @classmethod
    def validate_bill_id(cls, v: str) -> str:
        return _validate_non_empty_str(v, "bill_id")


class TopCEAPSpenderInput(BaseModel):
    """Parâmetros para consulta do ranking de maiores gastadores de cota parlamentar."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    casa: Literal["camara", "senado"] = Field(
        ...,
        description="Casa legislativa consultada ('camara' ou 'senado').",
    )
    ano: int = Field(
        ...,
        description="Ano de referência dos gastos da cota.",
    )
    top_n: int = Field(
        default=1,
        ge=1,
        le=100,
        description="Quantidade de posições no ranking (padrão: 1).",
    )

    @field_validator("casa", mode="before")
    @classmethod
    def normalize_casa(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.strip().lower()
        return v


class ResolvePoliticianInput(BaseModel):
    """Parâmetros de entrada para a ferramenta de resolução e desambiguação de parlamentares."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    nome_busca: str = Field(
        ...,
        description="Nome civil, nome de urna ou apelido citado na alegação.",
    )
    uf: Optional[str] = Field(
        default=None,
        description="Sigla da UF para desambiguação de homônimos.",
    )
    cargo: Optional[str] = Field(
        default=None,
        description="Cargo político de referência (ex: 'Deputado Federal', 'Senador').",
    )
    ano: Optional[int] = Field(
        default=None,
        description="Ano ou legislatura de referência.",
    )

    @field_validator("nome_busca")
    @classmethod
    def validate_nome_busca(cls, v: str) -> str:
        return _validate_non_empty_str(v, "nome_busca")


class ResolvePropositionInput(BaseModel):
    """Parâmetros de entrada para resolução de matérias e proposições legislativas."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    casa: Literal["camara", "senado", "congresso"] = Field(
        ...,
        description="Casa legislativa em que a proposição tramita.",
    )
    sigla_tipo: Optional[str] = Field(
        default=None,
        description="Sigla da proposição (ex: 'PL', 'PEC', 'MPV').",
    )
    numero: Optional[int] = Field(
        default=None,
        ge=1,
        description="Número formal da proposição.",
    )
    ano: Optional[int] = Field(
        default=None,
        description="Ano de apresentação da proposição.",
    )
    termo_busca: Optional[str] = Field(
        default=None,
        description="Termo livre ou nome popular da proposição para busca textual na ementa.",
    )


class InstitutionalRuleInput(BaseModel):
    """Parâmetros de consulta para a base curada de regras institucionais e regimentais."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    topico: str = Field(
        ...,
        description="Identificador canônico ou slug do tópico institucional consultado.",
    )

    @field_validator("topico")
    @classmethod
    def validate_topico(cls, v: str) -> str:
        return _validate_non_empty_str(v, "topico")


class DataSourceCoverageInput(BaseModel):
    """Parâmetros de consulta sobre disponibilidade e cobertura de fontes primárias de dados."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    fonte: str = Field(
        ...,
        description="Identificador da fonte oficial (ex: 'portal_transparencia', 'camara_frequencia').",
    )
    tipo_dado: str = Field(
        ...,
        description="Tipo de informação ou dado consultado.",
    )

    @field_validator("fonte")
    @classmethod
    def validate_fonte(cls, v: str) -> str:
        return _validate_non_empty_str(v, "fonte")

    @field_validator("tipo_dado")
    @classmethod
    def validate_tipo_dado(cls, v: str) -> str:
        return _validate_non_empty_str(v, "tipo_dado")


class ParliamentaryExpensesInput(BaseModel):
    """Parâmetros analíticos para verificação de despesas parlamentares (CEAP/CEAPS)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    casa: Literal["camara", "senado"] = Field(
        ...,
        description="Casa legislativa ('camara' ou 'senado').",
    )
    ano: int = Field(
        ...,
        description="Ano dos reembolsos da cota.",
    )
    parlamentar_id: Optional[str] = Field(
        default=None,
        description="ID numérico ou canônico do parlamentar.",
    )
    categoria: Optional[str] = Field(
        default=None,
        description="Categoria de despesa (ex: 'COMBUSTÍVEIS E LUBRIFICANTES').",
    )
    mes: Optional[int] = Field(
        default=None,
        ge=1,
        le=12,
        description="Mês de competência (1 a 12).",
    )


# ---------------------------------------------------------------------------
# Modelo de Saída Unificado (Tool Execution Output)
# ---------------------------------------------------------------------------

class ToolExecutionResult(BaseModel):
    """Contrato de saída unificado para o payload retornado por qualquer ferramenta do agente.

    Garante tipagem estrita, rastreabilidade da fonte e metadados de auditoria.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    status: str = Field(
        ...,
        description="Status da execução da ferramenta (ex: 'success', 'not_found', 'error').",
    )
    data: Dict[str, Any] = Field(
        ...,
        description="Payload estruturado com os dados retornados pela consulta oficial.",
    )
    source_url: str = Field(
        ...,
        description="URL oficial, endpoint da API pública ou URI do arquivo de proveniência dos dados.",
    )
    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Carimbo temporal UTC de captura da evidência para auditoria e rastreabilidade.",
    )

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        return _validate_non_empty_str(v, "status")

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, v: str) -> str:
        return _validate_non_empty_str(v, "source_url")
