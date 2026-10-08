"""Catálogo de tools do agente de fact-checking político brasileiro."""

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
from src.tools.resolve_politician import resolve_politician
from src.tools.resolve_proposition import resolve_proposition

__all__ = [
    "check_institutional_rule",
    "check_data_source_coverage",
    "INSTITUTIONAL_TOPICS",
    "DATA_SOURCES",
    "get_proposition_tramitation_history",
    "check_bill_apensamentos",
    "is_thematic_commission",
    "resolve_politician",
    "resolve_proposition",
]
