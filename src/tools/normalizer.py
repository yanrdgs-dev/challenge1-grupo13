"""Módulo de normalização de texto para o catálogo de tools de fact-checking.

Atende ao Princípio II da Constituição (matching determinístico por nome normalizado).
"""

import re
import unicodedata
from typing import Optional


def strip_accents(text: Optional[str]) -> str:
    """Remove diacríticos e acentos preservando o texto em sua forma base.

    Args:
        text: String de entrada (ex: 'João', 'José', 'Tabata Cláudia').

    Returns:
        Texto sem acentos (ex: 'Joao', 'Jose', 'Tabata Claudia').
    """
    if not text:
        return ""
    nfkd_form = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in nfkd_form if not unicodedata.combining(c))


def normalize_text(text: Optional[str]) -> str:
    """Higieniza e normaliza texto para busca e matching canônico.

    Realiza:
    1. Conversão para minúsculas;
    2. Remoção de acentos e diacríticos;
    3. Remoção/substituição de pontuações pontuais e aspas;
    4. Eliminação de espaços múltiplos e remoção de espaços nas bordas.

    Args:
        text: String de busca (ex: '  Nikolas FERREIRA  ', 'Dr. Fulano').

    Returns:
        String limpa e normalizada (ex: 'nikolas ferreira', 'dr fulano').
    """
    if not text:
        return ""

    # Remove acentos
    cleaned = strip_accents(text)

    # Converte para minúsculas
    cleaned = cleaned.lower()

    # Trata aspas (ex: O'Neill -> oneill, 'Fake News' -> fake news)
    cleaned = re.sub(r"['’`]", "", cleaned)

    # Substitui caracteres de pontuação e traços por espaços
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)

    # Colapsa múltiplos espaços em branco e faz strip
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned
