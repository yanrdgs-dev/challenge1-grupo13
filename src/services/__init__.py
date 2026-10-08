"""Módulo de microsserviços do sistema de fact-checking multiagente."""

from src.services.url_scraper import extract_article, is_valid_url

__all__ = ["extract_article", "is_valid_url"]
