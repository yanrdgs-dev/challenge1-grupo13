"""Módulo de ingestão e extração de dados abertos."""

from src.ingestion.extractors import (
    scrape_dados_abertos_camara,
    scrape_dados_abertos_senado,
    scrape_dados_abertos_tse,
)

__all__ = [
    "scrape_dados_abertos_camara",
    "scrape_dados_abertos_senado",
    "scrape_dados_abertos_tse",
]
