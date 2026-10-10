"""Baixa as bases públicas da Câmara e do Senado para `datasets/`. A lógica está em src/etl/download_datasets.py."""

import sys

from src.etl.download_datasets import main

if __name__ == "__main__":
    sys.exit(main())
