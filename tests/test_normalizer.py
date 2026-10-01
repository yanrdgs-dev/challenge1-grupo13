"""Testes unitários para o módulo de normalização de texto (T003).

Em conformidade estrita com o Princípio VII (TDD) e Princípio VIII da Constituição.
"""

import pytest
from src.tools.normalizer import normalize_text, strip_accents


def test_strip_accents_basic():
    """Valida a remoção de diacríticos e acentos comuns em nomes em português."""
    assert strip_accents("João") == "Joao"
    assert strip_accents("José") == "Jose"
    assert strip_accents("Tabata Cláudia") == "Tabata Claudia"
    assert strip_accents("POMPEO DE MATTOS") == "POMPEO DE MATTOS"
    assert strip_accents("Ângelo Coronel") == "Angelo Coronel"
    assert strip_accents("Câmara & Senado") == "Camara & Senado"


def test_normalize_text_case_and_whitespace():
    """Valida conversão para minúsculas e limpeza de espaçamentos extras."""
    assert normalize_text("  Nikolas FERREIRA  ") == "nikolas ferreira"
    assert normalize_text("Tabata   Amaral") == "tabata amaral"
    assert normalize_text("\tPompeo\n\tde Mattos ") == "pompeo de mattos"


def test_normalize_text_diacritics_and_casing():
    """Valida combinação de remoção de acentos com padronização de caixa."""
    assert normalize_text("Acácio Favacho") == "acacio favacho"
    assert normalize_text("JOSÉ GUIMARÃES") == "jose guimaraes"
    assert normalize_text("Érika Hilton") == "erika hilton"


def test_normalize_text_punctuation_removal():
    """Valida remoção de pontuações irrelevantes (pontos, traços, aspas)."""
    assert normalize_text("Dr. Fulano") == "dr fulano"
    assert normalize_text("Dep.-Federal") == "dep federal"
    assert normalize_text("O'Neill") == "oneill"
    assert normalize_text("PL 'Fake News'") == "pl fake news"


def test_normalize_text_empty_and_edge_cases():
    """Valida tratamento seguro de strings vazias ou nulas."""
    assert normalize_text("") == ""
    assert normalize_text("   ") == ""
    assert normalize_text(None) == ""
