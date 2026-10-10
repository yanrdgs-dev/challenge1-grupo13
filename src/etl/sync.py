"""Sincroniza uma fonte: decide se há novidade, baixa e registra o estado."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

import httpx

from src.etl.download_datasets import DownloadInfo
from src.etl.freshness import Fingerprint, decide, head_fingerprint
from src.etl.ingestion_state import IngestionState

logger = logging.getLogger("ETL.Sync")


@dataclass(frozen=True)
class SyncOutcome:
    action: str  # baixado | sem_novidade | seria_baixado
    reason: str
    info: Optional[DownloadInfo] = None


def sync_item(
    item_id: str,
    url: str,
    *,
    refresh: str,
    state: IngestionState,
    client: httpx.Client,
    local_exists: bool,
    local_mtime: Optional[float],
    local_size: Optional[int],
    download: Callable[[bool], DownloadInfo],
    force: bool = False,
    dry_run: bool = False,
    dest: str = "",
) -> SyncOutcome:
    """Baixa `url` só se houver novidade. Em `dry_run` apenas informa; falha de download propaga."""
    record = state.get_file(item_id)
    prior = Fingerprint.from_dict(record["fingerprint"]) if record else None
    needs_head = local_exists and not force and refresh == "validators"
    remote = head_fingerprint(url, client) if needs_head else None

    decision = decide(
        refresh=refresh, local_exists=local_exists, local_mtime=local_mtime, local_size=local_size,
        prior=prior, remote=remote, force=force,
    )
    if decision.download:
        if dry_run:
            logger.info("[NOVIDADE] %s: %s", item_id, decision.reason)
            return SyncOutcome("seria_baixado", decision.reason)
        logger.info("[ATUALIZANDO] %s: %s", item_id, decision.reason)
        info = download(True)
        state.record_file(
            item_id, url=url, dest=dest, fingerprint=info.fingerprint, size=info.size, sha256=info.sha256,
            downloaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        state.save()
        return SyncOutcome("baixado", decision.reason, info)

    if decision.adopt and not dry_run:
        state.record_file(item_id, url=url, dest=dest, fingerprint=remote, size=local_size, sha256=None,
                          downloaded_at=None, adopted=True)
        state.save()
    logger.info("[SEM NOVIDADE] %s: %s", item_id, decision.reason)
    return SyncOutcome("sem_novidade", decision.reason)
