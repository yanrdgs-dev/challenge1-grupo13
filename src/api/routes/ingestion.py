"""Estado da última ingestão das bases públicas, lido do arquivo publicado junto dos parquets."""

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.etl.status import hours_since, is_stale, read_status_file

router = APIRouter()

DEFAULT_STALE_HOURS = 6.0  # a ingestão roda de hora em hora: seis horas sem sucesso já é problema


@router.get("/api/ingestion/status")
def ingestion_status():
    """Última execução da ingestão, novidades encontradas e se os dados estão desatualizados."""
    directory = Path(os.environ.get("PROCESSED_DIR", "data/processed"))
    status = read_status_file(directory)
    if status is None:
        raise HTTPException(
            status_code=404,
            detail="Status da ingestão indisponível: nenhuma ingestão publicou o arquivo de status ainda.",
        )
    now = datetime.now(timezone.utc)
    limit = float(os.environ.get("INGESTION_STALE_HOURS", DEFAULT_STALE_HOURS))
    age = hours_since(status.get("ultimo_sucesso_em"), now)
    status["ultimo_sucesso_ha_horas"] = round(age, 2) if age is not None else None
    status["desatualizada"] = is_stale(status, limit, now)
    return status
