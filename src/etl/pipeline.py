"""Pipeline de ingestão: download incremental (Câmara, Senado, TSE) -> build_parquet -> dim_politicos.

- Só baixa o que tem novidade na fonte (ETag/Last-Modified) e só reconstrói os parquets se algo mudou,
  se uma carga anterior ficou pendente ou se ainda não há parquets publicados.
- O build roda em um diretório de staging e só é publicado ao final: quem lê `processed/` (o router) nunca
  vê dados pela metade, e uma falha deixa os parquets atuais intactos.
- Um lock de arquivo impede duas execuções simultâneas (cron sobreposto): a segunda sai sem fazer nada.
- Qualquer download falho aborta antes do build (`--allow-partial` libera).
"""

import argparse
import fcntl
import json
import logging
import os
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional, Sequence

from src.etl.build_dim_politicos import build_and_save_dim_politicos
from src.etl.build_parquet import process_all_datasets
from src.etl.download_datasets import run_downloads
from src.etl.ingestion_state import IngestionState
from src.etl.tse_ckan import run_tse_downloads

logger = logging.getLogger("ETL.Pipeline")

INFO_FILE = "ingestion_info.json"
STATE_FILE = ".ingestion_state.json"
LOCK_FILE = ".ingestion.lock"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def ingestion_lock(path: Path) -> Iterator[bool]:
    """Lock exclusivo e não bloqueante. Entrega False se outra execução já o detém."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "w")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        handle.close()  # fechar o arquivo libera o lock


def write_ingestion_info(target_dir: Path, state: IngestionState) -> Path:
    """Grava, junto dos parquets, de onde veio cada dado e quando foi baixado (para o juiz citar a data)."""
    fontes = {
        item_id: {
            "url": rec.get("url"),
            "baixado_em": rec.get("downloaded_at"),
            "last_modified": (rec.get("fingerprint") or {}).get("last_modified"),
            "etag": (rec.get("fingerprint") or {}).get("etag"),
        }
        for item_id, rec in sorted(state.files.items())
    }
    datas = [f["baixado_em"] for f in fontes.values() if f["baixado_em"]]
    info = {"gerado_em": _now(), "dados_atualizados_em": max(datas) if datas else None, "fontes": fontes}
    target = target_dir / INFO_FILE
    target.write_text(json.dumps(info, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return target


def publish_staging(staging: Path, final: Path) -> None:
    """Troca cada entrada de primeiro nível de `final` pela de `staging` (rename atômico por entrada).

    Entradas de `final` que não existem em `staging` ficam como estão; as que existem são substituídas
    por inteiro, o que remove datasets que deixaram de ser gerados.
    """
    final.mkdir(parents=True, exist_ok=True)
    old = final / f".old-{os.getpid()}"
    try:
        for entry in sorted(staging.iterdir()):
            target = final / entry.name
            if target.exists():
                old.mkdir(exist_ok=True)
                os.replace(target, old / entry.name)
            os.replace(entry, target)
    finally:
        shutil.rmtree(old, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)


def _build_and_publish(datasets_dir: Path, processed_dir: Path, state: IngestionState) -> bool:
    staging = processed_dir.with_name(processed_dir.name + ".staging")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        build_failures: List = []
        summaries = process_all_datasets(datasets_dir=datasets_dir, output_base=staging, failures=build_failures)
        if build_failures:
            for name, error in build_failures:
                logger.error("build_parquet falhou em '%s': %s", name, error)
            return False
        if not summaries:
            logger.error("build_parquet não gerou nenhum dataset")
            return False
        build_and_save_dim_politicos(
            output_path=str(staging / "dim_politicos.parquet"),
            camara_deputados_path=str(staging / "camara" / "deputados.parquet"),
            senado_senadores_path=str(staging / "senado" / "senadores.parquet"),
            camara_ceap_pattern=str(staging / "camara" / "ceap" / "**" / "*.parquet"),
            tse_candidatos_pattern=str(staging / "tse" / "candidatos" / "**" / "*.parquet"),
        )
        write_ingestion_info(staging, state)
        publish_staging(staging, processed_dir)
        logger.info("Parquets publicados em %s (%d datasets + dim_politicos)", processed_dir, len(summaries))
        return True
    except Exception as e:  # noqa: BLE001 - qualquer falha do build vira código de saída; nada é publicado
        logger.error("Falha ao construir/publicar os parquets: %s", e, exc_info=True)
        return False
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def run_pipeline(
    datasets_dir: Path,
    processed_dir: Path,
    anos_tse: Sequence[int] = (2022, 2026),
    skip_download: bool = False,
    allow_partial: bool = False,
    force: bool = False,
    check_only: bool = False,
    force_build: bool = False,
) -> int:
    """Executa a ingestão e devolve o código de saída (0 = sucesso ou nada a fazer)."""
    datasets_dir, processed_dir = Path(datasets_dir), Path(processed_dir)
    with ingestion_lock(datasets_dir / LOCK_FILE) as acquired:
        if not acquired:
            logger.warning("Outra ingestão está em andamento (lock em %s); nada a fazer", datasets_dir / LOCK_FILE)
            return 0
        return _run_locked(datasets_dir, processed_dir, anos_tse, skip_download, allow_partial, force,
                           check_only, force_build)


def _run_locked(
    datasets_dir: Path, processed_dir: Path, anos_tse: Sequence[int], skip_download: bool,
    allow_partial: bool, force: bool, check_only: bool, force_build: bool,
) -> int:
    state = IngestionState.load(datasets_dir / STATE_FILE)
    started_at = _now()
    changes: List[str] = []
    failures: List = []

    if not skip_download:
        logger.info(">>> Etapa 1/2: %s <<<", "verificação de novidades (nada será baixado)" if check_only
                    else "download incremental das bases públicas")
        failures += run_downloads(datasets_dir, state=state, force=force, dry_run=check_only, changes=changes)
        if anos_tse:
            failures += run_tse_downloads(datasets_dir, list(anos_tse), state=state, force=force,
                                          dry_run=check_only, changes=changes)

    if check_only:
        if changes:
            logger.info("%d fonte(s) com novidade: %s", len(changes), ", ".join(changes))
        else:
            logger.info("Nenhuma novidade nas fontes")
        return 1 if failures else 0

    def finish(code: int, built: bool) -> int:
        state.record_run(started_at, _now(), code, downloaded=len(changes), built=built)
        state.save()
        return code

    if changes:
        state.pending_build = True  # sobrevive a uma falha: a próxima execução reconstrói
        state.save()
    if failures:
        logger.error("%d download(s) falharam:", len(failures))
        for f in failures:
            logger.error("  - %s", f)
        if not allow_partial:
            logger.error("Build abortado: use --allow-partial para montar parquet com dados incompletos.")
            return finish(1, built=False)
        logger.warning("Seguindo para o build com dados incompletos (--allow-partial).")

    need_build = (
        skip_download or force_build or state.pending_build or not (processed_dir / INFO_FILE).exists()
    )
    if not need_build:
        logger.info("Sem novidades e parquets já publicados: build ignorado")
        return finish(0, built=False)

    logger.info(">>> Etapa 2/2: build_parquet + dim_politicos <<<")
    if not _build_and_publish(datasets_dir, processed_dir, state):
        return finish(1, built=False)
    state.pending_build = False
    return finish(0, built=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingestão: download incremental das bases públicas -> build_parquet -> dim_politicos."
    )
    parser.add_argument("--datasets-dir", default="datasets", help="CSVs brutos (padrão: datasets)")
    parser.add_argument("--processed-dir", default="data/processed", help="saída em parquet (padrão: data/processed)")
    parser.add_argument("--tse-anos", type=int, nargs="*", default=[2022, 2026],
                        help="anos do TSE (padrão: 2022 2026; vazio = pula o TSE)")
    parser.add_argument("--check", action="store_true", help="só informa se há novidade nas fontes; não baixa nem constrói")
    parser.add_argument("--force", action="store_true", help="rebaixa tudo, mesmo sem novidade")
    parser.add_argument("--force-build", action="store_true", help="reconstrói os parquets mesmo sem novidade")
    parser.add_argument("--skip-download", action="store_true", help="só roda o build")
    parser.add_argument("--allow-partial", action="store_true", help="monta parquet mesmo com downloads falhos")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    return run_pipeline(
        Path(args.datasets_dir), Path(args.processed_dir),
        anos_tse=args.tse_anos, skip_download=args.skip_download, allow_partial=args.allow_partial,
        force=args.force, check_only=args.check, force_build=args.force_build,
    )


if __name__ == "__main__":
    sys.exit(main())
