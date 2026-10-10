#!/usr/bin/env bash
# Ingestão incremental das bases públicas (Câmara, Senado, TSE): download -> parquet -> publicação.
# Roda dentro da imagem do judge, que já tem src/ e as dependências de produção, com os dados em
# /srv/factcheck/data (datasets/ = CSVs brutos, processed/ = parquets lidos pelo router).
# Instalação e uso: docs/ingestion.md. Argumentos são repassados ao pipeline (--check, --force, ...).
set -euo pipefail

BASE=/srv/factcheck
GHCR_OWNER="${GHCR_OWNER:-yanrdgs-dev}"
IMAGE_TAG="$(cat "$BASE/.current_tag")"
# O build dos parquets do TSE chega a alguns GB; o limite impede que ele derrube a VM e os serviços.
MEMORY="${INGESTION_MEMORY:-4g}"

mkdir -p "$BASE/data/datasets" "$BASE/data/processed"

# --name: o Docker recusa uma segunda ingestão simultânea; o lock do pipeline cobre o resto.
exec docker run --rm --name factcheck-ingestion \
  --user "$(id -u):$(id -g)" \
  --memory "$MEMORY" --memory-swap "$MEMORY" \
  -v /srv/factcheck/data:/app/data \
  -e PYTHONUNBUFFERED=1 \
  "ghcr.io/${GHCR_OWNER}/factcheck-judge:${IMAGE_TAG}" \
  python -m src.etl.pipeline \
    --datasets-dir /app/data/datasets --processed-dir /app/data/processed "$@"
