"""Módulo de rotas da API FastAPI."""

from src.api.routes.factcheck import router as factcheck_router
from src.api.routes.verify_url import router as verify_url_router

__all__ = [
    "factcheck_router",
    "verify_url_router",
]
