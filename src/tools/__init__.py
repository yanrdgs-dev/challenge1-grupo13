"""Catálogo de tools do agente de fact-checking político brasileiro."""

from typing import Any, Dict, List, Optional

# Exportará a função canônica resolve_politician conforme implementada
__all__ = ["resolve_politician"]


def __getattr__(name: str) -> Any:
    if name == "resolve_politician":
        from src.tools.resolve_politician import resolve_politician
        return resolve_politician
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
