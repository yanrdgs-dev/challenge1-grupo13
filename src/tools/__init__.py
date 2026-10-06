"""Módulo de ferramentas (tools) para o agente de fact-checking político."""

from src.tools.knowledge_tools import (
    DATA_SOURCES,
    INSTITUTIONAL_TOPICS,
    check_data_source_coverage,
    check_institutional_rule,
)
from src.tools.legislativo_tools import (
    check_bill_apensamentos,
    get_proposition_tramitation_history,
    is_thematic_commission,
)

__all__ = [
    "check_institutional_rule",
    "check_data_source_coverage",
    "INSTITUTIONAL_TOPICS",
    "DATA_SOURCES",
    "get_proposition_tramitation_history",
    "check_bill_apensamentos",
    "is_thematic_commission",
]
