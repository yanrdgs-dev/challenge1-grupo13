#!/usr/bin/env bash
# Ingestão incremental das bases públicas (Câmara, Senado, TSE): download -> parquet -> publicação.
# Roda dentro da imagem do judge, que já tem src/ e as dependências de produção, com os dados em
# /srv/factcheck/data (datasets/ = CSVs brutos, processed/ = parquets lidos pelo router).
# Instalação, avisos e uso: docs/ingestion.md. Argumentos vão para o pipeline (--status, --check, --force...).
set -euo pipefail

BASE=/srv/factcheck
# Variáveis de aviso (INGESTION_WEBHOOK_URL, INGESTION_HEARTBEAT_URL, INGESTION_NOTIFY). Arquivo próprio e
# opcional: nunca o .env dos serviços, que tem as chaves de LLM e do Langfuse.
ENV_FILE=/srv/factcheck/ingestion.env
GHCR_OWNER="${GHCR_OWNER:-yanrdgs-dev}"
IMAGE_TAG="$(cat "$BASE/.current_tag")"
# O build dos parquets do TSE chega a alguns GB; o limite impede que ele derrube a VM e os serviços.
MEMORY="${INGESTION_MEMORY:-4g}"

mkdir -p "$BASE/data/datasets" "$BASE/data/processed"

ENV_ARGS=()
[ -f "$ENV_FILE" ] && ENV_ARGS=(--env-file "$ENV_FILE")

# Lê KEY=valor do arquivo sem executá-lo (as URLs têm ? e &, que o shell interpretaria).
env_value() { [ -f "$ENV_FILE" ] && grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }

# Se o container morre sem o pipeline conseguir avisar (falta de memória = 137, erro do Docker = 125),
# avisa daqui. Falhas que o próprio pipeline trata (código 1) ele já avisou.
notify_crash() {
  local rc="$1" hb webhook text
  hb="$(env_value INGESTION_HEARTBEAT_URL)"
  webhook="$(env_value INGESTION_WEBHOOK_URL)"
  text="A ingestão encerrou de forma inesperada (código $rc; 137 = sem memória, 125 = erro do Docker). Veja: journalctl -u factcheck-ingestion"
  [ -n "$hb" ] && curl -fsS -m 10 -o /dev/null "${hb%/}/fail" || true
  [ -n "$webhook" ] || return 0
  case "$webhook" in
    *discord*) curl -fsS -m 10 -o /dev/null -H 'Content-Type: application/json' -d "{\"content\":\"**Ingestão caiu**\\n$text\"}" "$webhook" || true ;;
    *slack*)   curl -fsS -m 10 -o /dev/null -H 'Content-Type: application/json' -d "{\"text\":\"*Ingestão caiu*\\n$text\"}" "$webhook" || true ;;
    *ntfy*)    curl -fsS -m 10 -o /dev/null -H 'Title: Ingestao caiu' -d "$text" "$webhook" || true ;;
    *)         curl -fsS -m 10 -o /dev/null -H 'Content-Type: application/json' -d "{\"title\":\"Ingestão caiu\",\"text\":\"$text\"}" "$webhook" || true ;;
  esac
}

# Consultas (--status, --check) não geram alerta de queda.
QUERY_ONLY=0
for arg in "$@"; do
  case "$arg" in --status|--check) QUERY_ONLY=1 ;; esac
done

# --name: o Docker recusa uma segunda ingestão simultânea; o lock do pipeline cobre o resto.
set +e
docker run --rm --name factcheck-ingestion \
  --user "$(id -u):$(id -g)" \
  --memory "$MEMORY" --memory-swap "$MEMORY" \
  -v /srv/factcheck/data:/app/data \
  -e PYTHONUNBUFFERED=1 \
  "${ENV_ARGS[@]}" \
  "ghcr.io/${GHCR_OWNER}/factcheck-judge:${IMAGE_TAG}" \
  python -m src.etl.pipeline \
    --datasets-dir /app/data/datasets --processed-dir /app/data/processed "$@"
rc=$?
set -e

# 0 = ok; 1 = falha tratada pelo pipeline (já avisou); 2 = --status com dados desatualizados.
if [ "$QUERY_ONLY" -eq 0 ] && [ "$rc" -ne 0 ] && [ "$rc" -ne 1 ]; then
  notify_crash "$rc"
fi
exit $rc
