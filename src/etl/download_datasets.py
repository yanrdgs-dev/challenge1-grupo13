"""Download dos datasets públicos (Câmara e Senado) para `datasets/`.

Todo download é por streaming para um arquivo `.part`, conferido contra o `Content-Length` e só então
renomeado para o destino. Qualquer falha (timeout, rede, HTTP de erro, download parcial) vira
`DownloadError` e nunca deixa arquivo corrompido no destino.
"""

import argparse
import hashlib
import logging
import os
import sys
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import httpx

from src.etl.freshness import Fingerprint, HostBreaker
from src.etl.ingestion_state import IngestionState
from src.etl.manifest import Source, expand_sources, load_manifest
from src.etl.sync import sync_item

logger = logging.getLogger("ETL.Download")

USER_AGENT = "factcheck-agent/0.1 (+dados abertos; ingestao automatica)"
MIN_VALID_SIZE = 1000


RETRY_ATTEMPTS = 3
RETRY_BACKOFF = (2.0, 6.0)  # espera antes da 2ª e da 3ª tentativa


class DownloadError(Exception):
    """Falha explícita de download: parcial, rede, timeout, HTTP de erro ou zip inválido."""


class TransientDownloadError(DownloadError):
    """Falha que pode passar sozinha (timeout, rede, HTTP 5xx, download parcial): vale tentar de novo."""


@dataclass(frozen=True)
class DownloadInfo:
    path: Path
    size: Optional[int]
    sha256: Optional[str]
    skipped: bool
    fingerprint: Optional[Fingerprint]


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def make_client(read_timeout: float = 180.0) -> httpx.Client:
    """Client HTTP com verificação SSL ligada (padrão do httpx) e redirecionamentos seguidos.

    O servidor da Câmara chega a ficar mais de 60 s sem enviar bytes em arquivos grandes: o timeout de
    leitura é folgado, o de conexão não.
    """
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        timeout=httpx.Timeout(30.0, read=read_timeout),
        follow_redirects=True,
    )


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:  # diretório de zip ou arquivo já removido: limpeza é best-effort
        pass


def _stream_to_part(url: str, part: Path, desc: str, client: httpx.Client) -> tuple:
    """Baixa `url` para `part` e devolve (bytes gravados, sha256, impressão digital HTTP).

    Confere o Content-Length se informado.
    """
    written = 0
    digest = hashlib.sha256()
    try:
        with client.stream("GET", url) as resp:
            if resp.status_code >= 500:
                raise TransientDownloadError(f"{desc}: HTTP {resp.status_code} em {url}")
            if resp.status_code >= 400:
                raise DownloadError(f"{desc}: HTTP {resp.status_code} em {url}")
            fingerprint = Fingerprint.from_headers(resp.headers)
            expected = resp.headers.get("Content-Length")
            if resp.headers.get("Content-Encoding", "identity") != "identity":
                expected = None  # Content-Length refere-se aos bytes comprimidos, não aos decodificados
            with open(part, "wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
    except httpx.TimeoutException as e:
        raise TransientDownloadError(f"{desc}: timeout em {url}: {e}") from e
    except httpx.HTTPError as e:
        raise TransientDownloadError(f"{desc}: erro de rede em {url}: {e}") from e

    if expected is not None and expected.isdigit() and int(expected) != written:
        raise TransientDownloadError(
            f"{desc}: download parcial, Content-Length={expected} mas {written} bytes recebidos"
        )
    return written, digest.hexdigest(), fingerprint


def download_file(
    url: str,
    dest_path: Path,
    desc: str,
    client: Optional[httpx.Client] = None,
    expected_sha256: Optional[str] = None,
    force: bool = False,
) -> DownloadInfo:
    """Baixa `url` para `dest_path` de forma atômica. Pula se já existe um arquivo válido (salvo `force`).

    Com `expected_sha256`, um conteúdo diferente é `DownloadError` e nada é gravado.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if not force and dest_path.exists() and dest_path.stat().st_size > MIN_VALID_SIZE:
        logger.info("[PULANDO] %s já existe (%.1f KB)", desc, dest_path.stat().st_size / 1024)
        return DownloadInfo(dest_path, dest_path.stat().st_size, None, True, None)

    own_client = client is None
    client = client or make_client()
    part = dest_path.with_name(dest_path.name + ".part")
    logger.info("[BAIXANDO] %s de %s", desc, url)
    start = time.time()
    try:
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                size, sha256, fingerprint = _stream_to_part(url, part, desc, client)
                break
            except TransientDownloadError as e:
                _unlink(part)
                if attempt == RETRY_ATTEMPTS:
                    raise
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)) - 1]
                logger.warning("%s (tentativa %d/%d); nova tentativa em %.0fs", e, attempt, RETRY_ATTEMPTS, wait)
                _sleep(wait)
        if expected_sha256 and sha256 != expected_sha256:
            raise DownloadError(f"{desc}: sha256 diverge (esperado {expected_sha256}, obtido {sha256})")
        os.replace(part, dest_path)
    except OSError as e:
        _unlink(part)
        raise DownloadError(f"{desc}: erro de disco ao gravar {dest_path}: {e}") from e
    except BaseException:
        _unlink(part)
        raise
    finally:
        if own_client:
            client.close()
    logger.info("Concluído: %s (%.2f MB em %.1fs)", desc, size / 1024 / 1024, time.time() - start)
    return DownloadInfo(dest_path, size, sha256, False, fingerprint)


def _safe_extract(zip_path: Path, extract_dir: Path, desc: str) -> None:
    """Extrai o zip recusando membros que escapem de `extract_dir`.

    Extrai primeiro para um diretório temporário e só então move os arquivos para o destino: se algo
    falhar, os arquivos extraídos anteriormente continuam intactos.
    """
    root = extract_dir.resolve()
    staging = Path(tempfile.mkdtemp(dir=root, prefix=".extract-"))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = zf.infolist()
            for member in members:
                target = (root / member.filename).resolve()
                if root != target and root not in target.parents:
                    raise DownloadError(f"{desc}: zip com caminho inseguro ({member.filename})")
            bad = zf.testzip()
            if bad is not None:
                raise DownloadError(f"{desc}: zip corrompido em {bad}")
            for member in members:
                zf.extract(member, staging)
        for member in members:
            if member.is_dir():
                continue
            final = root / member.filename
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / member.filename, final)
    except zipfile.BadZipFile as e:
        raise DownloadError(f"{desc}: arquivo zip inválido: {e}") from e
    except OSError as e:
        raise DownloadError(f"{desc}: erro de disco ao extrair: {e}") from e
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def download_zip_csv(
    url: str,
    extract_dir: Path,
    expected_file_prefix: str,
    desc: str,
    client: Optional[httpx.Client] = None,
    expected_sha256: Optional[str] = None,
    force: bool = False,
) -> DownloadInfo:
    """Baixa um zip e extrai o CSV em `extract_dir`. Pula se o CSV esperado já está lá (salvo `force`).

    Devolve os dados do zip baixado (tamanho, sha256, validadores HTTP).
    """
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    existing = list(extract_dir.glob(f"{expected_file_prefix}*.csv"))
    if not force and existing and existing[0].stat().st_size > MIN_VALID_SIZE:
        logger.info("[PULANDO] %s já descompactado (%s)", desc, existing[0].name)
        return DownloadInfo(existing[0], existing[0].stat().st_size, None, True, None)

    zip_path = extract_dir / f"{expected_file_prefix}.zip.tmp"
    _unlink(zip_path)  # sobra de execução interrompida seria tratada como download válido
    try:
        info = download_file(url, zip_path, desc, client=client, expected_sha256=expected_sha256)
        _safe_extract(zip_path, extract_dir, desc)
        return info
    finally:
        _unlink(zip_path)


def local_zip_state(directory: Path, prefix: str, recorded: bool = False) -> tuple:
    """(existe, mtime mais recente, None) dos CSVs extraídos de um zip, identificados pelo prefixo.

    Alguns zips (ex.: prestação de contas do TSE) contêm CSVs com nome diferente do zip. Se a carga já
    foi registrada no estado (`recorded`), qualquer CSV no diretório conta como a cópia local.
    """
    files = [f for f in Path(directory).glob(f"{prefix}*.csv") if f.stat().st_size > MIN_VALID_SIZE]
    if not files and recorded:
        files = [f for f in Path(directory).glob("*.csv") if f.stat().st_size > MIN_VALID_SIZE]
    if not files:
        return False, None, None
    return True, max(f.stat().st_mtime for f in files), None


def _local_file_state(path: Path) -> tuple:
    if path.exists() and path.stat().st_size > MIN_VALID_SIZE:
        stat = path.stat()
        return True, stat.st_mtime, stat.st_size
    return False, None, None


def _download_source(source: Source, base_dir: Path, client: httpx.Client) -> None:
    dest = base_dir / source.dest
    if source.kind == "zip_csv":
        download_zip_csv(source.url, dest, source.prefix, source.desc, client=client,
                         expected_sha256=source.sha256)
    else:
        download_file(source.url, dest, source.desc, client=client, expected_sha256=source.sha256)


def _sync_source(
    source: Source, base_dir: Path, client: httpx.Client, state: IngestionState, force: bool, dry_run: bool,
    breaker: Optional[HostBreaker] = None,
):
    dest = base_dir / source.dest
    if source.kind == "zip_csv":
        record = state.get_file(source.id)
        exists, mtime, size = local_zip_state(dest, source.prefix, recorded=bool(record and record.get("downloaded_at")))

        def do(force_: bool) -> DownloadInfo:
            return download_zip_csv(source.url, dest, source.prefix, source.desc, client=client,
                                    expected_sha256=source.sha256, force=force_)
    else:
        exists, mtime, size = _local_file_state(dest)

        def do(force_: bool) -> DownloadInfo:
            return download_file(source.url, dest, source.desc, client=client,
                                 expected_sha256=source.sha256, force=force_)

    return sync_item(
        source.id, source.url, refresh=source.refresh, state=state, client=client, local_exists=exists,
        local_mtime=mtime, local_size=size, download=do, force=force, dry_run=dry_run, dest=source.dest,
        breaker=breaker,
    )


def run_downloads(
    base_dir: Path,
    client: Optional[httpx.Client] = None,
    manifest: Optional[dict] = None,
    state: Optional[IngestionState] = None,
    force: bool = False,
    dry_run: bool = False,
    changes: Optional[List[str]] = None,
) -> List[DownloadError]:
    """Baixa as fontes do manifesto. Falhas não interrompem as demais e são devolvidas ao chamador.

    Sem `state`, pula o que já existe em disco. Com `state`, baixa só o que tem novidade (ver
    `freshness.decide`), registra o estado e acrescenta a `changes` o id de cada fonte atualizada
    (ou que seria atualizada, em `dry_run`).
    """
    base_dir = Path(base_dir)
    sources = expand_sources(manifest if manifest is not None else load_manifest())
    own_client = client is None
    client = client or make_client()
    failures: List[DownloadError] = []
    breaker = HostBreaker()
    try:
        for source in sources:
            try:
                if state is None:
                    _download_source(source, base_dir, client)
                else:
                    outcome = _sync_source(source, base_dir, client, state, force, dry_run, breaker)
                    if changes is not None and outcome.action != "sem_novidade":
                        changes.append(source.id)
            except DownloadError as e:
                logger.error("%s", e)
                failures.append(e)
    finally:
        if own_client:
            client.close()
    return failures


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Baixa as bases públicas da Câmara e do Senado.")
    parser.add_argument("--base-dir", default="datasets", help="diretório de destino (padrão: datasets)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    failures = run_downloads(Path(args.base_dir))
    if failures:
        logger.error("%d download(s) falharam", len(failures))
        return 1
    logger.info("Todos os downloads concluídos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
