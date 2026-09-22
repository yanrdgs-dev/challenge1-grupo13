"""Pacote de schemas de validação e contratos de dados."""

from src.schemas.data_schemas import (
    CAMARA_CEAP_COLUMNS,
    CAMARA_VOTACOES_COLUMNS,
    DATA_SCHEMAS,
    TSE_BENS_COLUMNS,
    TSE_CANDIDATOS_COLUMNS,
    TSE_DESPESAS_COLUMNS,
    detect_schema_by_columns,
    get_schema_columns,
)

__all__ = [
    "DATA_SCHEMAS",
    "TSE_DESPESAS_COLUMNS",
    "TSE_CANDIDATOS_COLUMNS",
    "TSE_BENS_COLUMNS",
    "CAMARA_VOTACOES_COLUMNS",
    "CAMARA_CEAP_COLUMNS",
    "get_schema_columns",
    "detect_schema_by_columns",
]
