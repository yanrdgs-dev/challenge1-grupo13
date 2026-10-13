"""Cache em memória para indexação ultrarrápida de parlamentares.

Otimizado para atender a requisitos de latência inferior a 50ms (SC-005)
e suportar matching exato O(1) e fuzzy matching via RapidFuzz.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import polars as pl

from src.tools.normalizer import normalize_text


logger = logging.getLogger(__name__)


class PoliticianCache:
    """Mantém em memória o catálogo canônico de parlamentares indexado para busca."""

    _instance: Optional["PoliticianCache"] = None

    def __init__(self, parquet_path: str = "data/processed/dim_politicos.parquet"):
        self.parquet_path = parquet_path
        self._signature: Optional[Tuple[int, int]] = None  # (mtime_ns, tamanho) do parquet carregado
        self.records: List[Dict[str, Any]] = []
        # Índices exatos para busca O(1)
        self.civil_index: Dict[str, List[Dict[str, Any]]] = {}
        self.urna_index: Dict[str, List[Dict[str, Any]]] = {}
        # Corpus para busca fuzzy: [(nome_civil_norm, nome_urna_norm, record)]
        self.fuzzy_corpus: List[Tuple[str, str, Dict[str, Any]]] = []
        self._load()

    def _file_signature(self) -> Optional[Tuple[int, int]]:
        try:
            st = Path(self.parquet_path).stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def _load(self) -> None:
        path = Path(self.parquet_path)
        if not path.exists():
            return

        signature = self._file_signature()
        df = pl.read_parquet(path)
        self.load_from_dataframe(df)
        self._signature = signature

    def reload_if_changed(self) -> bool:
        """Recarrega se a ingestão publicou uma versão nova do parquet.

        Um arquivo ilegível ou ausente mantém o catálogo anterior: melhor dado antigo e consistente do que
        nenhum. A publicação da ingestão troca o arquivo por renomeação, então a leitura nunca vê meio arquivo.
        """
        signature = self._file_signature()
        if signature is None or signature == self._signature:
            return False
        try:
            df = pl.read_parquet(self.parquet_path)
        except Exception as e:  # noqa: BLE001 - arquivo corrompido ou em troca: mantém o catálogo atual
            logger.warning("dim_politicos.parquet ilegível (%s); mantendo o catálogo anterior", e)
            return False
        self.load_from_dataframe(df)
        self._signature = signature
        logger.info("dim_politicos recarregado: %d registros", len(self.records))
        return True

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
        else:
            cls._instance.reload_if_changed()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reinicia o singleton (útil para testes unitários com fixtures isoladas)."""
        cls._instance = None
