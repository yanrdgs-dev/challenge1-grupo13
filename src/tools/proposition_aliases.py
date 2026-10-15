"""Apelidos de proposições: o nome que a imprensa usa ("PEC da escala 6x1") → sigla, número e ano oficiais.

O apelido quase nunca está na ementa (a da PEC 221/2019 fala em 'jornada de trabalho de 36 horas'), então a busca
por nome na API não o encontra. A base curada em ``knowledge/proposition_aliases.json`` faz essa ponte; o resolvedor
continua sendo quem confirma o ID e a Casa. Para incluir uma proposição, basta acrescentar uma entrada ao JSON.
"""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

ALIASES_FILE = Path(__file__).parent / "knowledge" / "proposition_aliases.json"


def _normalize(text: str) -> str:
    """Minúsculas, sem acentos, '6 x 1' → '6x1' e espaços colapsados."""
    folded = "".join(c for c in unicodedata.normalize("NFKD", (text or "").lower()) if not unicodedata.combining(c))
    folded = re.sub(r"(\d)\s*x\s*(\d)", r"\1x\2", folded)
    return re.sub(r"\s+", " ", folded).strip()


@lru_cache(maxsize=1)
def load_aliases() -> List[Dict[str, Any]]:
    return json.loads(ALIASES_FILE.read_text(encoding="utf-8"))


def find_alias(text: str) -> Optional[Dict[str, Any]]:
    """A proposição cujo apelido aparece no texto; None se nenhuma, ou se o texto cita apelidos de duas diferentes."""
    normalized = _normalize(text)
    if not normalized:
        return None
    hits: Dict[str, Dict[str, Any]] = {}
    for entry in load_aliases():
        for apelido in entry["apelidos"]:
            if re.search(rf"(?<!\w){re.escape(_normalize(apelido))}(?!\w)", normalized):
                hits[entry["id"]] = entry
                break
    return next(iter(hits.values())) if len(hits) == 1 else None
