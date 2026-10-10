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
import time
import zipfile
from pathlib import Path
from typing import List, Optional

import httpx

from src.etl.manifest import Source, expand_sources, load_manifest

logger = logging.getLogger("ETL.Download")

USER_AGENT = "factcheck-agent/0.1 (+dados abertos; ingestao automatica)"
MIN_VALID_SIZE = 1000


class DownloadError(Exception):
    """Falha explícita de download: parcial, rede, timeout, HTTP de erro ou zip inválido."""


def make_client(timeout: float = 60.0) -> httpx.Client:
    """Client HTTP com verificação SSL ligada (padrão do httpx) e redirecionamentos seguidos."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        timeout=timeout,
        follow_redirects=True,
    )


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:  # diretório de zip ou arquivo já removido: limpeza é best-effort
        pass


def _stream_to_part(url: str, part: Path, desc: str, client: httpx.Client) -> tuple:
    """Baixa `url` para `part` e devolve (bytes gravados, sha256); confere o Content-Length se informado."""
    written = 0
    digest = hashlib.sha256()
    try:
        with client.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise DownloadError(f"{desc}: HTTP {resp.status_code} em {url}")
            expected = resp.headers.get("Content-Length")
            if resp.headers.get("Content-Encoding", "identity") != "identity":
                expected = None  # Content-Length refere-se aos bytes comprimidos, não aos decodificados
            with open(part, "wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
    except httpx.TimeoutException as e:
        raise DownloadError(f"{desc}: timeout em {url}: {e}") from e
    except httpx.HTTPError as e:
        raise DownloadError(f"{desc}: erro de rede em {url}: {e}") from e

    if expected is not None and expected.isdigit() and int(expected) != written:
        raise DownloadError(
            f"{desc}: download parcial, Content-Length={expected} mas {written} bytes recebidos"
        )
    return written, digest.hexdigest()


def download_file(
    url: str,
    dest_path: Path,
    desc: str,
    client: Optional[httpx.Client] = None,
    expected_sha256: Optional[str] = None,
) -> Path:
    """Baixa `url` para `dest_path` de forma atômica. Pula se já existe um arquivo válido.

    Com `expected_sha256`, um conteúdo diferente é `DownloadError` e nada é gravado.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists() and dest_path.stat().st_size > MIN_VALID_SIZE:
        logger.info("[PULANDO] %s já existe (%.1f KB)", desc, dest_path.stat().st_size / 1024)
        return dest_path

    own_client = client is None
    client = client or make_client()
    part = dest_path.with_name(dest_path.name + ".part")
    logger.info("[BAIXANDO] %s de %s", desc, url)
    start = time.time()
    try:
        size, sha256 = _stream_to_part(url, part, desc, client)
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
    return dest_path


def _safe_extract(zip_path: Path, extract_dir: Path, desc: str) -> List[Path]:
    """Extrai o zip recusando membros que escapem de `extract_dir`; desfaz se algo falhar."""
    root = extract_dir.resolve()
    extracted: List[Path] = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.infolist():
                target = (root / member.filename).resolve()
                if root != target and root not in target.parents:
                    raise DownloadError(f"{desc}: zip com caminho inseguro ({member.filename})")
            bad = zf.testzip()
            if bad is not None:
                raise DownloadError(f"{desc}: zip corrompido em {bad}")
            for member in zf.infolist():
                extracted.append(root / member.filename)  # antes de extrair: cobre arquivo parcial
                zf.extract(member, root)
    except zipfile.BadZipFile as e:
        raise DownloadError(f"{desc}: arquivo zip inválido: {e}") from e
    except OSError as e:
        for path in extracted:
            _unlink(path)
        raise DownloadError(f"{desc}: erro de disco ao extrair: {e}") from e
    except BaseException:
        for path in extracted:
            _unlink(path)
        raise
    return extracted


def download_zip_csv(
    url: str,
    extract_dir: Path,
    expected_file_prefix: str,
    desc: str,
    client: Optional[httpx.Client] = None,
    expected_sha256: Optional[str] = None,
) -> None:
    """Baixa um zip e extrai o CSV em `extract_dir`. Pula se o CSV esperado já está lá."""
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    existing = list(extract_dir.glob(f"{expected_file_prefix}*.csv"))
    if existing and existing[0].stat().st_size > MIN_VALID_SIZE:
        logger.info("[PULANDO] %s já descompactado (%s)", desc, existing[0].name)
        return

    zip_path = extract_dir / f"{expected_file_prefix}.zip.tmp"
    try:
        download_file(url, zip_path, desc, client=client, expected_sha256=expected_sha256)
        _safe_extract(zip_path, extract_dir, desc)
    finally:
        _unlink(zip_path)


def _download_source(source: Source, base_dir: Path, client: httpx.Client) -> None:
    dest = base_dir / source.dest
    if source.kind == "zip_csv":
        download_zip_csv(source.url, dest, source.prefix, source.desc, client=client,
                         expected_sha256=source.sha256)
    else:
        download_file(source.url, dest, source.desc, client=client, expected_sha256=source.sha256)


def run_downloads(
    base_dir: Path, client: Optional[httpx.Client] = None, manifest: Optional[dict] = None
) -> List[DownloadError]:
    """Baixa as fontes do manifesto. Falhas não interrompem as demais e são devolvidas ao chamador."""
    base_dir = Path(base_dir)
    sources = expand_sources(manifest if manifest is not None else load_manifest())
    own_client = client is None
    client = client or make_client()
    failures: List[DownloadError] = []
    try:
        for source in sources:
            try:
                _download_source(source, base_dir, client)
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
