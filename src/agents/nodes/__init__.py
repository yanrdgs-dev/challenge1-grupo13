"""Módulo de nós dos agentes do pipeline de fact-checking."""

from src.agents.nodes.article_aggregator import (
    ARTICLE_AGGREGATOR_SYSTEM_PROMPT,
    ArticleAggregationResult,
    ArticleAggregator,
    article_aggregator_node,
)
from src.agents.nodes.claim_extractor import (
    CLAIM_EXTRACTOR_SYSTEM_PROMPT,
    ClaimExtractor,
    claim_extractor_node,
)
from src.schemas.claims import AtomicClaim

__all__ = [
    "ARTICLE_AGGREGATOR_SYSTEM_PROMPT",
    "ArticleAggregationResult",
    "ArticleAggregator",
    "article_aggregator_node",
    "AtomicClaim",
    "CLAIM_EXTRACTOR_SYSTEM_PROMPT",
    "ClaimExtractor",
    "claim_extractor_node",
]
