"""Detecção de novidades nas fontes: impressão digital HTTP e decisão de baixar ou não.

Os portais públicos expõem validadores (ETag, Last-Modified) na maioria dos arquivos. Quando existem,
comparamos com o que foi registrado na última carga; quando não, o manifesto marca a fonte como
`refresh: always` (pequena e dinâmica) ou comparamos o tamanho.
"""

import logging
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("ETL.Freshness")


@dataclass(frozen=True)
class Fingerprint:
    etag: Optional[str]
    last_modified: Optional[str]
    content_length: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return {"etag": self.etag, "last_modified": self.last_modified, "content_length": self.content_length}

    @staticmethod
    def from_dict(data: Optional[Dict[str, Any]]) -> Optional["Fingerprint"]:
        if not data:
            return None
        return Fingerprint(data.get("etag"), data.get("last_modified"), data.get("content_length"))

    @staticmethod
    def from_headers(headers: httpx.Headers) -> "Fingerprint":
        length = headers.get("Content-Length")
        return Fingerprint(
            etag=headers.get("ETag"),
            last_modified=headers.get("Last-Modified"),
            content_length=int(length) if length and length.isdigit() else None,
        )


@dataclass(frozen=True)
class Decision:
    download: bool
    reason: str
    adopt: bool = False  # cópia local aceita como base: registrar a impressão digital remota sem baixar


def head_fingerprint(url: str, client: httpx.Client) -> Optional[Fingerprint]:
    """Impressão digital via HEAD. None se o servidor não respondeu direito (nunca levanta)."""
    try:
        resp = client.head(url)
    except httpx.HTTPError as e:
        logger.warning("HEAD falhou em %s: %s", url, e)
        return None
    if resp.status_code >= 400:
        logger.warning("HEAD %s devolveu HTTP %d", url, resp.status_code)
        return None
    return Fingerprint.from_headers(resp.headers)


def _timestamp(http_date: str) -> Optional[float]:
    try:
        return parsedate_to_datetime(http_date).timestamp()
    except (TypeError, ValueError):
        return None


def decide(
    refresh: str,
    local_exists: bool,
    local_mtime: Optional[float],
    local_size: Optional[int],
    prior: Optional[Fingerprint],
    remote: Optional[Fingerprint],
    force: bool,
) -> Decision:
    """Decide se a fonte precisa ser baixada. `prior` é o que a última carga registrou."""
    if force:
        return Decision(True, "forçado")
    if not local_exists:
        return Decision(True, "arquivo local ausente")
    if refresh == "always":
        return Decision(True, "fonte dinâmica (refresh=always)")
    if remote is None:
        return Decision(False, "não foi possível verificar o remoto (HEAD falhou); mantém a cópia local")

    if remote.etag or remote.last_modified:
        if prior and (prior.etag or prior.last_modified):
            if prior.etag and remote.etag and prior.etag != remote.etag:
                return Decision(True, f"ETag mudou ({prior.etag} -> {remote.etag})")
            if prior.last_modified and remote.last_modified and prior.last_modified != remote.last_modified:
                return Decision(True, f"Last-Modified mudou ({prior.last_modified} -> {remote.last_modified})")
            return Decision(False, "sem novidade")
        remote_ts = _timestamp(remote.last_modified) if remote.last_modified else None
        if remote_ts is not None and local_mtime is not None:
            if remote_ts > local_mtime:
                return Decision(True, "remoto mais novo que o arquivo local")
            return Decision(False, "cópia local é mais nova que o remoto", adopt=True)
        return Decision(False, "sem base de comparação; assume a cópia local", adopt=True)

    if remote.content_length is None:
        return Decision(False, "remoto sem validadores nem tamanho; mantém a cópia local")
    if prior and prior.content_length is not None:
        if prior.content_length != remote.content_length:
            return Decision(True, f"tamanho mudou ({prior.content_length} -> {remote.content_length})")
        return Decision(False, "sem novidade")
    if local_size is not None and local_size != remote.content_length:
        return Decision(True, f"tamanho diferente da cópia local ({local_size} -> {remote.content_length})")
    return Decision(False, "sem base de comparação; assume a cópia local", adopt=True)
