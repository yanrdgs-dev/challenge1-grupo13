"""Envia o golden_dataset_v2.json ao Langfuse de forma idempotente (upsert por id).

Uso:
    uv run python scripts/langfuse_sync_dataset.py            # envia
    uv run python scripts/langfuse_sync_dataset.py --dry-run  # só valida o arquivo
"""

import argparse
import sys
from pathlib import Path
from typing import Callable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.dataset import DatasetSyncError, load_golden_dataset, sync_golden_dataset  # noqa: E402

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "golden_dataset_v2.json"


def _langfuse_client():
    from dotenv import load_dotenv
    from langfuse import get_client

    load_dotenv()
    return get_client()


def main(argv: Optional[List[str]] = None, client_factory: Callable = _langfuse_client) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", default=str(DEFAULT_PATH), help="Caminho do golden dataset.")
    parser.add_argument("--dry-run", action="store_true", help="Valida o arquivo sem chamar o Langfuse.")
    args = parser.parse_args(argv)

    try:
        items = load_golden_dataset(args.path)
        client = None if args.dry_run else client_factory()
        summary = sync_golden_dataset(client, items, dry_run=args.dry_run, dataset_name=Path(args.path).stem)
    except (ValueError, DatasetSyncError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    mode = "validado (dry-run)" if args.dry_run else "sincronizado"
    print(f"Dataset '{summary['dataset']}' {mode}: {summary['items']} itens.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
