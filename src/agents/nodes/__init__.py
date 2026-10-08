"""Módulo de nós dos agentes do pipeline de fact-checking."""

from src.agents.nodes.claim_extractor import (
    CLAIM_EXTRACTOR_SYSTEM_PROMPT,
    ClaimExtractor,
    claim_extractor_node,
)
from src.schemas.claims import AtomicClaim

__all__ = [
    "AtomicClaim",
    "CLAIM_EXTRACTOR_SYSTEM_PROMPT",
    "ClaimExtractor",
    "claim_extractor_node",
]
