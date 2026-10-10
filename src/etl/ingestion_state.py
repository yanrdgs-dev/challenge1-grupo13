"""Estado persistente da ingestão: o que foi baixado, quando, e a impressão digital de cada fonte."""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.etl.freshness import Fingerprint

logger = logging.getLogger("ETL.State")

STATE_VERSION = 1
HISTORY_LIMIT = 50
MAX_CHANGES = 30  # ids de fontes guardados por execução (o total fica em `downloaded`)
MAX_FAILURES = 5


def origin_of(item_id: str) -> str:
    """Origem de uma fonte pelo prefixo do id (camara, senado, tse)."""
    return item_id.split("-", 1)[0]


def count_by_origin(item_ids: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item_id in item_ids:
        counts[origin_of(item_id)] = counts.get(origin_of(item_id), 0) + 1
    return counts


class IngestionState:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.files: Dict[str, Dict[str, Any]] = {}
        self.pending_build = False  # há dados novos ainda não convertidos em parquet
        self.deferred: List[str] = []  # novidades de fontes que não disparam build, aguardando o próximo
        self.last_run: Optional[Dict[str, Any]] = None
        self.history: List[Dict[str, Any]] = []  # últimas execuções, da mais antiga para a mais nova
        self.notify: Dict[str, Any] = {}  # memória dos avisos (evita repetir a mesma falha a cada hora)

    @classmethod
    def load(cls, path: Path) -> "IngestionState":
        state = cls(path)
        if not state.path.exists():
            return state
        try:
            data = json.loads(state.path.read_text(encoding="utf-8"))
            state.files = dict(data.get("files", {}))
            state.pending_build = bool(data.get("pending_build", False))
            state.deferred = list(data.get("deferred", []))
            state.last_run = data.get("last_run")
            state.history = list(data.get("history", []))
            state.notify = dict(data.get("notify", {}))
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as e:
            backup = state.path.with_name(state.path.name + ".corrupt")
            logger.error("Estado ilegível em %s (%s); guardado em %s e recomeçando vazio", state.path, e, backup)
            os.replace(state.path, backup)
            state.files, state.pending_build, state.last_run = {}, False, None
            state.deferred = []
            state.history, state.notify = [], {}
        return state

    def get_file(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self.files.get(item_id)

    def record_file(
        self,
        item_id: str,
        url: str,
        dest: str,
        fingerprint: Optional[Fingerprint],
        size: Optional[int],
        sha256: Optional[str],
        downloaded_at: Optional[str],
        adopted: bool = False,
    ) -> None:
        self.files[item_id] = {
            "url": url,
            "dest": dest,
            "fingerprint": fingerprint.to_dict() if fingerprint else None,
            "size": size,
            "sha256": sha256,
            "downloaded_at": downloaded_at,
            "adopted": adopted,
        }

    def record_run(
        self,
        started_at: str,
        finished_at: str,
        exit_code: int,
        downloaded: int,
        built: bool,
        changes: Optional[List[str]] = None,
        failures: Optional[List[str]] = None,
        deferred: int = 0,
    ) -> None:
        run = {
            "started_at": started_at, "finished_at": finished_at,
            "exit_code": exit_code, "downloaded": downloaded, "built": built,
            "changes": list(changes or [])[:MAX_CHANGES],
            "changes_by_origin": count_by_origin(list(changes or [])),  # contado antes de truncar os ids
            "failures": [str(f) for f in (failures or [])][:MAX_FAILURES],
            "deferred": deferred,  # quantas das novidades não disparam build (Senado)
        }
        self.last_run = run
        self.history = (self.history + [dict(run)])[-HISTORY_LIMIT:]

    def save(self) -> None:
        """Grava de forma atômica: nunca deixa um estado pela metade."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": STATE_VERSION, "files": self.files,
            "pending_build": self.pending_build, "last_run": self.last_run,
            "history": self.history, "notify": self.notify, "deferred": self.deferred,
        }
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
