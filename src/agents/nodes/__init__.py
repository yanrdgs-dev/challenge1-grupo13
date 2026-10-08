"""Nós do grafo de agentes para o sistema de fact-checking."""

from src.agents.nodes.synthesizer import (
    CLOSED_BOOK_SYSTEM_PROMPT,
    SynthesizerOutput,
    build_synthesizer_prompt,
    is_empty_payload,
    synthesizer_node,
)

__all__ = [
    "synthesizer_node",
    "SynthesizerOutput",
    "CLOSED_BOOK_SYSTEM_PROMPT",
    "build_synthesizer_prompt",
    "is_empty_payload",
]
