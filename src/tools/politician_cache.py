"""Cache em memória para indexação ultrarrápida de parlamentares.

Otimizado para atender a requisitos de latência inferior a 50ms (SC-005)
e suportar matching exato O(1) e fuzzy matching via RapidFuzz.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import polars as pl

from src.tools.normalizer import normalize_text


class PoliticianCache:
    """Mantém em memória o catálogo canônico de parlamentares indexado para busca."""

    _instance: Optional["PoliticianCache"] = None

    def __init__(self, parquet_path: str = "data/processed/dim_politicos.parquet"):
        self.parquet_path = parquet_path
        self.records: List[Dict[str, Any]] = []
        # Índices exatos para busca O(1)
        self.civil_index: Dict[str, List[Dict[str, Any]]] = {}
        self.urna_index: Dict[str, List[Dict[str, Any]]] = {}
        # Corpus para busca fuzzy: [(nome_civil_norm, nome_urna_norm, record)]
        self.fuzzy_corpus: List[Tuple[str, str, Dict[str, Any]]] = []
        self._load()

    def _load(self) -> None:
        path = Path(self.parquet_path)
        if not path.exists():
            return

        df = pl.read_parquet(path)
        self.load_from_dataframe(df)

    def load_from_dataframe(self, df: pl.DataFrame) -> None:
        """Carrega e indexa registros a partir de um DataFrame do Polars."""
        self.records = df.to_dicts()
        self.civil_index = {}
        self.urna_index = {}
        self.fuzzy_corpus = []

        for record in self.records:
            civil_norm = record.get("nome_normalizado") or normalize_text(record.get("nome_civil"))
            urna_norm = normalize_text(record.get("nome_urna"))

            # Indexa pelo nome civil normalizado
            if civil_norm:
                self.civil_index.setdefault(civil_norm, []).append(record)

            # Indexa pelo nome de urna normalizado
            if urna_norm:
                self.urna_index.setdefault(urna_norm, []).append(record)

            self.fuzzy_corpus.append((civil_norm, urna_norm, record))

    @classmethod
    def get_instance(cls, parquet_path: str = "data/processed/dim_politicos.parquet") -> "PoliticianCache":
        if cls._instance is None:
            cls._instance = cls(parquet_path)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reinicia o singleton (útil para testes unitários com fixtures isoladas)."""
        cls._instance = None
