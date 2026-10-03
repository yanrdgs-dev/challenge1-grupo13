# Tasks: Resolução Canônica de Proposições (`resolve_proposition`)

**Feature**: `002-resolve-proposition`  
**Spec**: [specs/002-resolve-proposition/spec.md](spec.md)  
**Plan**: [specs/002-resolve-proposition/plan.md](plan.md)  

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Definição de contratos, tipos auxiliares e utilitários de normalização de siglas legislativas.

- [X] T001 Configure proposition schemas and data structures in src/tools/resolve_proposition.py
- [X] T002 [P] Implement legislative acronym normalizer function in src/tools/normalizer.py
- [X] T003 [P] Write unit tests for legislative acronym normalizer in tests/test_normalizer.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Implementação do cliente HTTP especializado para as APIs de Dados Abertos da Câmara e do Senado com timeout e cache de sessão.

**⚠️ CRITICAL**: Nenhuma User Story pode ser implementada antes da conclusão desta fase.

- [X] T004 Write unit tests for LegislativeClient with mocked HTTP responses and timeouts in tests/test_legislative_client.py
- [X] T005 Implement LegislativeClient with 5s timeout and in-memory session cache in src/tools/legislative_client.py
- [X] T006 Implement network fault and timeout interceptors in src/tools/legislative_client.py

**Checkpoint**: Cliente HTTP legislativo pronto e testado com isolamento 100% offline via mocks.

---

## Phase 3: User Story 1 - Resolução Direta por Identificadores Formais (Priority: P1) 🎯 MVP

**Goal**: Resolver proposições com identificadores formais (sigla_tipo, numero, ano) na Câmara e no Senado para IDs canônicos oficiais (`id_proposicao`).

**Independent Test**: Invocação com `casa="camara", sigla_tipo="PL", numero=2630, ano=2020` retornando `id_proposicao=2253965` e `ambiguous: false`.

### Tests for User Story 1 (TDD Obrigatório - Escrever antes do código funcional) ⚠️

- [X] T007 [P] [US1] Write unit tests for exact Câmara resolution (PL 2630/2020) with mocked API responses in tests/test_resolve_proposition.py
- [X] T008 [P] [US1] Write unit tests for exact Senado resolution (PEC 45/2019) with mocked API responses in tests/test_resolve_proposition.py
- [X] T009 [P] [US1] Write unit test verifying JSON Schema contract compliance in tests/test_resolve_proposition.py

### Implementation for User Story 1

- [X] T010 [US1] Implement exact query resolution workflow for Câmara in src/tools/resolve_proposition.py
- [X] T011 [US1] Implement exact query resolution workflow for Senado and Congresso in src/tools/resolve_proposition.py
- [X] T012 [US1] Add parameter validation ensuring casa is valid and mandatory criteria exist in src/tools/resolve_proposition.py
- [X] T013 [US1] Export resolve_proposition function in src/tools/__init__.py

**Checkpoint**: User Story 1 100% funcional e testável de forma independente (MVP concluído).

---

## Phase 4: User Story 2 - Resolução por Nome Popular ou Tema na Ementa (Priority: P2)

**Goal**: Identificar matérias através de nomes populares consagrados (ex.: "Marco Temporal", "Reforma Tributária") combinando busca por palavra-chave na API e RapidFuzz na ementa.

**Independent Test**: Consulta por `casa="camara", termo_busca="Marco Temporal", ano=2023` resolvendo para a proposição correta com `ambiguous: false`.

### Tests for User Story 2 (TDD Obrigatório) ⚠️

- [X] T014 [P] [US2] Write unit tests for thematic search and popular name matching in tests/test_resolve_proposition.py
- [X] T015 [P] [US2] Write unit tests for non-existent proposition searches asserting structured not-found in tests/test_resolve_proposition.py

### Implementation for User Story 2

- [X] T016 [US2] Implement thematic search and ementa scoring with RapidFuzz in src/tools/resolve_proposition.py
- [X] T017 [US2] Implement structured not-found response handler when API returns empty in src/tools/resolve_proposition.py

**Checkpoint**: User Stories 1 e 2 funcionais e integradas de forma determinística.

---

## Phase 5: User Story 3 - Detecção de Ambiguidade em Claims Vagas para Decisão de Inconclusivo (Priority: P3)

**Goal**: Identificar termos temáticos amplos e genéricos (ex.: "segurança pública", "área fiscal" - Claims 26 e 30 do Golden Dataset), retornando `ambiguous: true` com a lista de matérias alternativas para fundamentar veredito `INCONCLUSIVO` do roteador.

**Independent Test**: Consulta por `casa="senado", termo_busca="segurança pública"` retornando `ambiguous: true`, `id_proposicao: None` e lista de `candidatos`.

### Tests for User Story 3 (TDD Obrigatório) ⚠️

- [X] T018 [P] [US3] Write unit tests for generic terms asserting ambiguous=True and populated candidatos in tests/test_resolve_proposition.py
- [X] T019 [P] [US3] Write network fault and timeout tolerance unit tests simulating ConnectTimeout in tests/test_resolve_proposition.py

### Implementation for User Story 3

- [X] T020 [US3] Implement ambiguity detection logic with score delta clustering in src/tools/resolve_proposition.py
- [X] T021 [US3] Populate candidatos response array with PropositionCandidateSummary items in src/tools/resolve_proposition.py
- [X] T022 [US3] Implement exception handling for network timeouts and HTTP errors returning clean structured responses in src/tools/resolve_proposition.py

**Checkpoint**: Todas as 3 User Stories concluídas e testadas independentemente.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Verificação de performance, regressão, ausência de chamadas de rede em testes e documentação.

- [X] T023 [P] Execute complete test suite in tests/test_resolve_proposition.py and tests/test_legislative_client.py
- [X] T024 Run performance and cache hit verification in tests/test_resolve_proposition.py
- [X] T025 Execute end-to-end quickstart validation scenarios in specs/002-resolve-proposition/quickstart.md
- [X] T026 [P] Update tool documentation and implementation status in docs/tools_specification.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Sem dependências prévias — inicialização imediata.
- **Foundational (Phase 2)**: Depende do Setup — **BLOQUEIA** todas as User Stories (cliente HTTP com timeout e cache).
- **User Stories (Phases 3, 4, 5)**: Dependem estritamente da Fase 2 (Foundational).
  - Sequência: US1 (P1 - Busca Formal) → US2 (P2 - Nome Popular) → US3 (P3 - Detecção de Ambiguidade).
- **Polish (Phase 6)**: Executada após a conclusão das User Stories.

### Within Each User Story (Ciclo TDD Inegociável - Princípio VII)

1. **RED**: Escrever os testes unitários com mocks e garantir que falham antes do código.
2. **GREEN**: Implementar a lógica necessária para tornar os testes verdes.
3. **REFACTOR**: Refatorar código e tipagem mantendo a suíte verde.

---

## Parallel Opportunities

- **Setup**: `T002` e `T003` (normalizador de siglas e seus testes) podem rodar em paralelo.
- **Testes por Story**: Testes unitários com mocks (`T007`, `T008`, `T009` na US1; `T014`, `T015` na US2; `T018`, `T019` na US3) podem ser redigidos em paralelo.
- **Polish**: `T023` e `T026` podem rodar em paralelo.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Executar Fase 1: Setup (`T001` - `T003`).
2. Executar Fase 2: Foundational (`T004` - `T006`) implementando o cliente HTTP legislativo.
3. Executar Fase 3: User Story 1 (`T007` - `T013`).
4. **Validar MVP**: Executar `pytest tests/test_resolve_proposition.py -k test_exact_resolution`.
5. Fazer commit: `feat(tools): implementa resolve_proposition para busca formal exata`.
