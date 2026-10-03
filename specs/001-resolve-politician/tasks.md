# Tasks: Resolução Canônica de Parlamentares (`resolve_politician`)

**Feature**: `001-resolve-politician`  
**Spec**: [specs/001-resolve-politician/spec.md](spec.md)  
**Plan**: [specs/001-resolve-politician/plan.md](plan.md)  

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Inicialização da infraestrutura do módulo de tools e dependências do projeto.

- [X] T001 Configure project dependencies in requirements.txt ensuring rapidfuzz>=3.0.0 is present
- [X] T002 [P] Create tools directory structure and package initialization in src/tools/__init__.py
- [X] T003 [P] Write unit tests for text normalization in tests/test_normalizer.py
- [X] T004 Implement text normalization functions in src/tools/normalizer.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Construção da base dimensional canônica unificada (`dim_politicos.parquet`) que bloqueia todas as User Stories.

**⚠️ CRITICAL**: Nenhuma User Story pode ser implementada antes da conclusão desta fase.

- [X] T005 Write unit tests for dimensional ETL in tests/test_build_dim_politicos.py
- [X] T006 Implement canonical politician dimensional ETL builder in src/etl/build_dim_politicos.py
- [X] T007 Materialize local parquet database data/processed/dim_politicos.parquet via build_dim_politicos.py
- [X] T008 [P] Implement in-memory table loader and index cache in src/tools/politician_cache.py

**Checkpoint**: Base de dados `dim_politicos.parquet` materializada e indexador em memória pronto.

---

## Phase 3: User Story 1 - Resolução Canônica Direta de Parlamentar (Priority: P1) 🎯 MVP

**Goal**: Resolver nomes próprios inequívocos (civis, de urna e com variações ortográficas/acentos) para o perfil canônico com IDs da Câmara (`ideCadastro`), Senado (`cod_senador`) e TSE (`sq_candidato`).

**Independent Test**: Invocação direta da função com "Nikolas Ferreira" ou "Tabata Amaral" retornando a entidade esperada com `ambiguous: false` e identificadores preenchidos.

### Tests for User Story 1 (TDD Obrigatório - Escrever antes do código funcional) ⚠️

- [X] T009 [P] [US1] Write contract and direct resolution unit tests in tests/test_resolve_politician.py
- [X] T010 [P] [US1] Write offline isolation and CPF absence unit tests in tests/test_resolve_politician.py

### Implementation for User Story 1

- [X] T011 [US1] Implement exact normalized dictionary lookup in src/tools/resolve_politician.py
- [X] T012 [US1] Implement fuzzy matching fallback with RapidFuzz in src/tools/resolve_politician.py
- [X] T013 [US1] Add input parameter validation and error handling in src/tools/resolve_politician.py
- [X] T014 [US1] Export resolve_politician function in src/tools/__init__.py

**Checkpoint**: User Story 1 100% funcional e testável de forma independente (MVP concluído).

---

## Phase 4: User Story 2 - Detecção e Tratamento de Homônimos e Ambiguidade (Priority: P2)

**Goal**: Detectar múltiplos candidatos concorrentes com nomes idênticos/próximos, sinalizando `ambiguous: true` com alternativas, ou desambiguando automaticamente via `uf` e `cargo`.

**Independent Test**: Consultar nome comum sem UF (retorna `ambiguous: true` com alternativas) e em seguida fornecer `uf="RJ"` (retorna entidade única desambiguada com `ambiguous: false`).

### Tests for User Story 2 (TDD Obrigatório) ⚠️

- [X] T015 [P] [US2] Write ambiguity and homonym detection unit tests in tests/test_resolve_politician.py
- [X] T016 [P] [US2] Write state (UF) and office (cargo) disambiguation unit tests in tests/test_resolve_politician.py

### Implementation for User Story 2

- [X] T017 [US2] Implement ambiguity clustering and score delta logic in src/tools/resolve_politician.py
- [X] T018 [US2] Implement state (UF) and office (cargo) post-matching filters in src/tools/resolve_politician.py
- [X] T019 [US2] Populate candidatos_alternativos response structure in src/tools/resolve_politician.py

**Checkpoint**: User Stories 1 e 2 funcionais e integradas de forma determinística.

---

## Phase 5: User Story 3 - Validação de Entidades Oriundas de Ferramentas de Ranking (Priority: P3)

**Goal**: Permitir que o Agente Sintetizador valide identidades de parlamentares retornadas por tools de gastos/votações (ex.: maior gastador da CEAP - Caso 1 do Golden Dataset) e trate termos não encontrados com retorno estruturado de `not found`.

**Independent Test**: Validar "Pompeo de Mattos" (PDT-RS) com dados originados de ranking analítico da CEAP, e verificar que personalidades inexistentes retornam `None` sem erros.

### Tests for User Story 3 (TDD Obrigatório) ⚠️

- [X] T020 [P] [US3] Write ranking validation unit test for Golden Dataset Case 1 in tests/test_resolve_politician.py
- [X] T021 [P] [US3] Write unknown entity handling unit test in tests/test_resolve_politician.py

### Implementation for User Story 3

- [X] T022 [US3] Implement ranking validation helper mode in src/tools/resolve_politician.py
- [X] T023 [US3] Implement structured not-found response handler in src/tools/resolve_politician.py

**Checkpoint**: Todas as 3 User Stories concluídas e testadas independentemente.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Verificação de performance, regressão, ausência de chamadas de rede e documentação.

- [X] T024 [P] Execute complete test suite in tests/test_resolve_politician.py and tests/test_normalizer.py
- [X] T025 Run latency and performance benchmark in tests/test_resolve_politician.py
- [X] T026 Execute end-to-end quickstart validation scenarios in specs/001-resolve-politician/quickstart.md
- [X] T027 [P] Update tool documentation and implementation status in docs/tools_specification.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Sem dependências prévias — inicialização imediata.
- **Foundational (Phase 2)**: Depende do Setup — **BLOQUEIA** todas as User Stories (materializa `dim_politicos.parquet`).
- **User Stories (Phases 3, 4, 5)**: Dependem estritamente da Fase 2 (Foundational).
  - Sequência recomendada: US1 (P1 - MVP) → US2 (P2 - Desambiguação) → US3 (P3 - Validação de Ranking).
- **Polish (Phase 6)**: Executada após a conclusão das User Stories desejadas.

### User Story Dependencies

- **US1 (P1)**: Não possui dependências de outras stories.
- **US2 (P2)**: Constrói sobre os mecanismos de matching da US1, adicionando clusterização de empates e filtros de UF/cargo.
- **US3 (P3)**: Utiliza a interface consolidada da US1 e US2 para validar saídas de ranking e garantir tratamento seguro de inexistência.

### Within Each User Story (Ciclo TDD Inegociável - Princípio VII)

1. **RED**: Escrever os testes unitários da história e garantir que falham antes do código.
2. **GREEN**: Implementar a lógica mínima necessária para tornar os testes verdes.
3. **REFACTOR**: Refatorar código e tipagem mantendo a suíte verde.

---

## Parallel Opportunities

- **Setup**: `T002` (criação de diretórios) e `T003` (testes do normalizador) podem rodar em paralelo.
- **Foundational**: `T008` (cache em memória) pode ser preparado em paralelo com `T005`/`T006`.
- **Testes por Story**: Todos os testes marcados com `[P]` (ex.: `T009` e `T010` na US1, `T015` e `T016` na US2) podem ser escritos em paralelo.
- **Polish**: `T024` e `T027` podem ser executadas em paralelo.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Executar Fase 1: Setup (`T001` - `T004`).
2. Executar Fase 2: Foundational (`T005` - `T008`) para materializar `dim_politicos.parquet`.
3. Executar Fase 3: User Story 1 (`T009` - `T014`).
4. **Validar MVP**: Executar `pytest tests/test_resolve_politician.py -k test_direct_resolution`.
5. Fazer commit: `feat(tools): implementa resolve_politician para resolucao direta`.

### Entrega Incremental

- Adicionar User Story 2 (`T015` - `T019`) → Testar homônimos e filtros de UF → Commit `feat(tools): adiciona suporte a desambiguacao de homonimos`.
- Adicionar User Story 3 (`T020` - `T023`) → Testar caso Pompeo de Mattos e entidades inexistentes → Commit `feat(tools): adiciona modo de validacao de ranking`.
- Executar Fase 6: Polish (`T024` - `T027`) → Garantir conformidade com os 10 princípios constitucionais.
