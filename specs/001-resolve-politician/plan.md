# Implementation Plan: Resolução Canônica de Parlamentares (`resolve_politician`)

**Branch**: `001-resolve-politician` | **Date**: 2026-10-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-resolve-politician/spec.md`

## Summary

Implementação da tool canônica de resolução e desambiguação de entidades parlamentares (`resolve_politician`), cumprindo o Princípio II e VIII da Constituição do projeto. A ferramenta resolve nomes próprios de parlamentares (civis, de urna e apelidos políticos) para seus respectivos identificadores unificados nas bases oficiais da Câmara dos Deputados (`ideCadastro`), Senado Federal (`cod_senador`) e TSE (`sq_candidato`). A arquitetura combina um primeiro estágio de lookup exato normalizado em memória ($O(1)$) com fallback para fuzzy matching conservador via RapidFuzz, operando 100% offline sobre a dimensão unificada `dim_politicos.parquet` sem qualquer dependência ou exposição de CPF.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `polars>=1.0.0`, `duckdb>=1.0.0`, `pyarrow>=15.0.0`, `rapidfuzz>=3.0.0`

**Storage**: Arquivo Apache Parquet local (`data/processed/dim_politicos.parquet`) indexado em memória para lookup determinístico.

**Testing**: `pytest>=8.0.0`, `pytest-mock>=3.14.0`

**Target Platform**: Execução local em ambiente Linux/macOS no pipeline do agente de fact-checking.

**Project Type**: Módulo Python de Tool do Catálogo do Agente de Fact-Checking (`src/tools/`).

**Performance Goals**: Latência de resolução inferior a 50 milissegundos por chamada (meta operacional $< 5$ ms para nomes normalizados indexados).

**Constraints**:
- Execução 100% offline (zero chamadas de rede durante a execução da tool e dos testes unitários).
- Proibição absoluta de uso de CPF para junções ou identificadores (Princípio II da Constituição).
- Resolução canônica obrigatória antes de qualquer chamada a tools transacionais de gastos ou votações.
- Retorno explícito de ambiguidade (`ambiguous: True`) diante de empates entre candidatos homônimos sem filtro discriminador.

**Scale/Scope**: Catálogo de parlamentares federais (Câmara dos Deputados e Senado Federal, legislaturas 56ª e 57ª), totalizando aproximadamente 1.500 a 2.500 registros consolidados.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Princípio Constitucional | Status | Avaliação Técnica & Racional |
|---|---|---|
| **I. Veredito Rastreável** | PASS | A tool fornece identificadores canônicos institucionais (`ideCadastro`, `cod_senador`, `sq_candidato`) rastreáveis às fontes oficiais. |
| **II. Resolução Canônica Obrigatória** | PASS | A feature é a materialização direta deste princípio, impedindo que tools a jusante recebam texto livre; joins utilizam exclusivamente nome normalizado + UF/cargo (sem CPF). |
| **III. Claims Subespecificadas** | PASS | Nomes não localizados ou com ambiguidades não resolvidas retornam status explícito de não-correspondência, permitindo ao agente sintetizador declarar veredito `INCONCLUSIVO`. |
| **IV. Separação de Dados e Normas** | PASS | Tool exclusivamente dimensional de entidades parlamentares; não infere regras regimentais. |
| **V. Golden Dataset como Portão** | PASS | Calibrada para validar o parlamentar do Caso 1 (`Pompeo de Mattos`) e dar suporte aos Casos 7 e 13 de `golden_dataset_v1.json`. |
| **VI. Neutralidade de Veredito** | PASS | Metadados neutros e objetivos; matching agnóstico de partido ou espectro ideológico. |
| **VII. TDD Inegociável** | PASS | A suíte de testes unitários (`tests/test_resolve_politician.py`) será implementada na etapa Red antes da codificação funcional da tool. |
| **VIII. Isolamento e Cobertura de Tools** | PASS | Cobertura garantida dos 4 quadrantes: caminho feliz, entidade não encontrada, homônimos/ambiguidade e teste 100% offline sem chamadas de rede. |
| **IX. Commits Convencionais** | PASS | Commits com escopo definido: `test(tools): cobre resolve_politician` seguido de `feat(tools): implementa resolve_politician`. |
| **X. Stack Unificada Python** | PASS | 100% Python, aproveitando Polars e DuckDB para Parquet local conforme `docs/data_schemas.md`. |

## Project Structure

### Documentation (this feature)

```text
specs/001-resolve-politician/
├── spec.md              # Especificação de negócio validada
├── checklists/
│   └── requirements.md  # Checklist de qualidade de requisitos
├── plan.md              # Este plano de implementação (/speckit-plan)
├── research.md          # Fase 0: Decisões técnicas e trade-offs
├── data-model.md        # Fase 1: Entidades, campos e estados
├── quickstart.md        # Fase 1: Guia prático de execução e validação
└── contracts/
    └── resolve_politician.json # Fase 1: Contrato JSON Schema da tool
```

### Source Code (repository root)

```text
src/
├── tools/
│   ├── __init__.py               # Exporta resolve_politician
│   ├── resolve_politician.py     # Lógica central de resolução e desambiguação
│   └── normalizer.py             # Normalização de nomes (acentos, caixa, apelidos)
├── etl/
│   ├── build_dim_politicos.py    # Pipeline ETL que materializa dim_politicos.parquet
│   └── build_parquet.py          # ETL existente de conversão de dados brutos
└── schemas/
    └── data_schemas.py           # Esquemas dimensionais do projeto

tests/
├── test_normalizer.py            # Testes unitários do normalizador de texto
├── test_resolve_politician.py    # Testes unitários dos 4 quadrantes da tool
└── test_build_dim_politicos.py   # Testes da materialização da tabela dimensional
```

**Structure Decision**: Criação do pacote `src/tools/` dedicado ao catálogo de tools do agente de fact-checking, isolando funções de normalização de texto em `normalizer.py` para reutilização nas demais tools legislativas e eleitorais.

## Complexity Tracking

| Violação | Justificativa | Alternativa Mais Simples Rejeitada Por Que |
|---|---|---|
| Nenhuma | N/A - Arquitetura estritamente alinhada aos princípios constitucionais e padrões já adotados no repositório. | N/A |
