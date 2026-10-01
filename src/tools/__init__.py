"""Módulo de ferramentas (tools) para o agente de fact-checking político."""

from src.tools.knowledge_tools import (
    DATA_SOURCES,
    INSTITUTIONAL_TOPICS,
    check_data_source_coverage,
    check_institutional_rule,
)

__all__ = [
    "check_institutional_rule",
    "check_data_source_coverage",
    "INSTITUTIONAL_TOPICS",
    "DATA_SOURCES",
]
