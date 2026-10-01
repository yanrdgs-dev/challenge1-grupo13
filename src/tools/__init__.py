"""Catálogo de tools para o agente de fact-checking."""

from src.tools.http_client import HttpClient, HttpNetworkError
from src.tools.votacoes_api import (
    get_proposition_vote_result,
    get_proposition_vote_breakdown,
    get_congress_veto_sessions,
    get_plenary_attendance,
)

__all__ = [
    "HttpClient",
    "HttpNetworkError",
    "get_proposition_vote_result",
    "get_proposition_vote_breakdown",
    "get_congress_veto_sessions",
    "get_plenary_attendance",
]
