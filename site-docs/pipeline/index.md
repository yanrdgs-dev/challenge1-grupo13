# Visão Geral do Pipeline

O pipeline do Factcheck Agent é composto por **8 etapas**, desde a coleta dos dados brutos oficiais até a entrega do veredito ao usuário final.

```mermaid
flowchart LR
    E1[🗄️ Etapa 1\nDados Brutos] --> E2[⚙️ Etapa 2\nETL / Parquet]
    E2 --> E3[🌐 Etapa 3\nIngestão Web]
    E3 --> E4[🔧 Etapa 4\nTools / Consulta]
    E4 --> E5[🤖 Etapa 5\nAgentes LLM]
    E5 --> E6[🔌 Etapa 6\nAPI / Serviços]
    E6 --> E7[🖥️ Etapa 7\nInterface]
    E7 --> E8[☸️ Etapa 8\nInfraestrutura]

    style E1 fill:#7C3AED,color:#fff
    style E2 fill:#2563EB,color:#fff
    style E3 fill:#0891B2,color:#fff
    style E4 fill:#059669,color:#fff
    style E5 fill:#D97706,color:#fff
    style E6 fill:#DC2626,color:#fff
    style E7 fill:#7C3AED,color:#fff
    style E8 fill:#374151,color:#fff
```

---

## Mapa de etapas × arquivos

| Etapa | Responsabilidade | Módulos Principais |
|---|---|---|
| [1 — Dados](01-dados.md) | Esquemas, seleção de colunas, mapeamento TSE e Câmara | `src/schemas/`, `docs/data_schemas.md` |
| [2 — ETL](02-etl.md) | Conversão CSV → Parquet (Polars, ZSTD, particionamento) | `src/etl/build_parquet.py`, `src/etl/build_dim_politicos.py` |
| [3 — Ingestão Web](03-ingestao.md) | Scraping portais TSE/Câmara/Senado e extração de notícias | `src/ingestion/extractors.py`, `src/services/url_scraper.py` |
| [4 — Tools](04-tools.md) | Catálogo de ferramentas de consulta e regras | `src/tools/` |
| [5 — Agentes](05-agentes.md) | Roteador, Sintetizador, LLM Client | `src/core/llm_client.py`, `src/services/` |
| [6 — API & Serviços](06-api.md) | FastAPI, contratos Pydantic, endpoints REST | `src/services/router_service.py`, `src/services/judge_service.py` |
| [7 — Interface](07-interface.md) | Frontend React + Vite (branch `interface`) | `frontend/` |
| [8 — Infraestrutura](08-infra.md) | Docker, Docker Compose e Kubernetes | `docker/`, `k8s/` |
