"""Pipeline de ingestão completo: download (Câmara, Senado, TSE) -> build_parquet.

Por padrão não monta parquet sobre downloads incompletos: qualquer falha aborta antes do build
(`--allow-partial` libera). Os downloads de Câmara/Senado e TSE sempre rodam por inteiro, para que
um erro apareça junto com todos os outros e não um por execução.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from src.etl.build_parquet import process_all_datasets
from src.etl.download_datasets import run_downloads
from src.etl.tse_ckan import run_tse_downloads

logger = logging.getLogger("ETL.Pipeline")


def run_pipeline(
    datasets_dir: Path,
    processed_dir: Path,
    anos_tse: Sequence[int] = (2022, 2026),
    skip_download: bool = False,
    allow_partial: bool = False,
) -> int:
    """Executa download -> build_parquet e devolve o código de saída (0 = sucesso)."""
    datasets_dir, processed_dir = Path(datasets_dir), Path(processed_dir)

    if not skip_download:
        logger.info(">>> Etapa 1/2: download das bases públicas <<<")
        failures = list(run_downloads(datasets_dir))
        if anos_tse:
            failures += run_tse_downloads(datasets_dir, list(anos_tse))
        if failures:
            logger.error("%d download(s) falharam:", len(failures))
            for f in failures:
                logger.error("  - %s", f)
            if not allow_partial:
                logger.error("Build abortado: use --allow-partial para montar parquet com dados incompletos.")
                return 1
            logger.warning("Seguindo para o build com dados incompletos (--allow-partial).")

    logger.info(">>> Etapa 2/2: build_parquet <<<")
    try:
        summaries = process_all_datasets(datasets_dir=datasets_dir, output_base=processed_dir)
    except Exception as e:  # noqa: BLE001 - qualquer falha do build vira código de saída
        logger.error("Falha no build_parquet: %s", e, exc_info=True)
        return 1
    if not summaries:
        logger.error("build_parquet não gerou nenhum dataset")
        return 1
    logger.info("Pipeline concluído: %d dataset(s) convertidos", len(summaries))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline: download das bases públicas -> build_parquet.")
    parser.add_argument("--datasets-dir", default="datasets", help="CSVs brutos (padrão: datasets)")
    parser.add_argument("--processed-dir", default="data/processed", help="saída em parquet (padrão: data/processed)")
    parser.add_argument("--tse-anos", type=int, nargs="*", default=[2022, 2026], help="anos do TSE (padrão: 2022 2026; vazio = pula o TSE)")
    parser.add_argument("--skip-download", action="store_true", help="só roda o build_parquet")
    parser.add_argument("--allow-partial", action="store_true", help="monta parquet mesmo com downloads falhos")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    return run_pipeline(
        Path(args.datasets_dir), Path(args.processed_dir),
        anos_tse=args.tse_anos, skip_download=args.skip_download, allow_partial=args.allow_partial,
    )


if __name__ == "__main__":
    sys.exit(main())
