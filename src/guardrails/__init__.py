"""Módulo de Guardrails do Agente de Fact-Checking Político Brasileiro.

Implementa a governança de inputs, roteamento de diálogo e auditoria determinística de outputs
conforme a Constituição em AGENTS.md.
"""

from src.guardrails.actions import (
    check_input_specificity,
    check_input_neutrality,
    audit_traceable_evidence,
)

__all__ = [
    "check_input_specificity",
    "check_input_neutrality",
    "audit_traceable_evidence",
]
