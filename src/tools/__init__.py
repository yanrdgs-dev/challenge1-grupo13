"""Módulo de ferramentas (tools) para o agente de fact-checking político."""

from src.tools.legislativo_tools import (
    check_bill_apensamentos,
    get_proposition_tramitation_history,
    is_thematic_commission,
)
from src.tools.resolve_politician import resolve_politician
from src.tools.resolve_proposition import resolve_proposition

__all__ = [
    "get_proposition_tramitation_history",
    "check_bill_apensamentos",
    "is_thematic_commission",
    "resolve_politician",
    "resolve_proposition"
  
]

