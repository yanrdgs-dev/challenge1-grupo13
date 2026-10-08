# Factcheck Agent

> **Agente de fact-checking político brasileiro** — verificação automática de afirmações sobre gastos, votações, proposições e regras institucionais, com veredito fundamentado em fontes oficiais rastreáveis.

---

## O que é este projeto?

O **Factcheck Agent** é um sistema multiagente de inteligência artificial que verifica automaticamente afirmações políticas brasileiras consultando bases de dados oficiais públicas. O projeto foi desenvolvido como parte do **Challenge 1 — Grupo 13** no programa de formação CBL.

O agente nunca emite um veredito sem citar uma fonte primária verificável. Se os dados forem insuficientes, o retorno é sempre **INCONCLUSIVO** — nunca um palpite.

---

## Vereditos possíveis

| Veredito | Significado |
|---|---|
| ✅ **VERDADEIRO** | A evidência primária confirma diretamente o fato alegado |
| ❌ **FALSO** | A evidência primária contradiz o fato alegado |
| ⚠️ **INCONCLUSIVO** | Os dados são insuficientes, a entidade é ambígua ou a alegação é subespecificada |

---

## Início rápido

```bash
# 1. Instalar dependências (Python 3.11+ e uv obrigatórios)
uv sync

# 2. Configurar variáveis de ambiente
cp .env.example .env
# Edite .env com sua chave GROQ_API_KEY ou aponte para Ollama local

# 3. Rodar a suíte de testes
uv run pytest

# 4. Subir o servidor (modo desenvolvimento)
uv run uvicorn src.services.router_service:app --reload
```

---

## Estrutura do repositório

```
challenge1-grupo13/
├── src/
│   ├── core/            # Cliente LLM (Ollama / Groq / OpenAI)
│   ├── database/        # DuckDB — camada de acesso analítico
│   ├── etl/             # Pipeline ETL: CSV → Parquet via Polars
│   ├── ingestion/       # Scraping de portais de dados abertos
│   ├── schemas/         # Esquemas e seleção de colunas oficiais
│   ├── services/        # Microsserviços FastAPI (Router e Judge)
│   └── tools/           # Catálogo completo de tools do agente
├── tests/               # Suíte TDD (todos os testes unitários)
├── datasets/            # Relatórios de EDA e scripts de análise
├── docs/                # Documentação técnica original
├── docker/              # Dockerfiles dos microsserviços
├── k8s/                 # Manifests Kubernetes
├── scripts/             # Scripts de demonstração e benchmark
└── golden_dataset_v1.json  # 30 alegações de referência para teste
```

---

## Métricas de qualidade

| Métrica | Valor |
|---|---|
| Testes unitários (em execução na `main`) | **151 passando** |
| Acurácia no Golden Dataset v1 | **93,3%** (28/30) |
| Casos do Golden Dataset | **30 claims** (12 V, 12 F, 6 I) |
| Cobertura de tools | Gastos, Votações, Legislativo, Regras Institucionais, Resolução de Entidade |

---

## Navegue pela documentação

- 🏗️ [**Arquitetura**](arquitetura.md) — visão macro do sistema multiagente
- ⚙️ [**Pipeline**](pipeline/index.md) — etapas de dados → veredito
- 📊 [**Golden Dataset**](golden-dataset.md) — conjunto de 30 alegações de referência
- 🧪 [**Testes**](testes.md) — filosofia TDD e cobertura da suíte
- 🤝 [**Contribuindo**](contribuindo.md) — padrões, branches e commits
