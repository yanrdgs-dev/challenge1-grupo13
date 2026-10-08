# Tasks: Tools do Grupo de Gastos (CEAP e CEAPS)

**Feature Branch**: `001-tools-gastos`  
**Input**: [specs/001-tools-gastos/spec.md](file:///Users/aluno2/Documents/Residencia/projeto_fakenews/challenge1-grupo13/specs/001-tools-gastos/spec.md) e [specs/001-tools-gastos/plan.md](file:///Users/aluno2/Documents/Residencia/projeto_fakenews/challenge1-grupo13/specs/001-tools-gastos/plan.md)  
**Status**: Completed  
**Constitution Principle VII (TDD Mandatório)**: Todo teste unitário DEVE ser escrito antes do código de produção e DEVE falhar antes da implementação mínima necessária.

---

## Phase 1: Setup & Fixtures de Teste

- [x] T001 Criar fixture de dados mock em `tests/test_gastos_tools.py` com amostras sintéticas de CEAP (Câmara) e CEAPS (Senado) em diretório temporário (`tmp_path`).
- [x] T002 Configurar estrutura de diretórios `src/tools/` caso ainda não exista no workspace local.

---

## Phase 2: Foundational (Modelos Estruturados e Resolução de Dados)

- [x] T003 Escrever testes unitários em `tests/test_gastos_tools.py` para os schemas de dados (`TopSpenderItem`, `TopSpenderResponse`, `ExpenseCategoryItem`, `ExpenseCategoriesResponse`, `ExpenseAuditResult`).
- [x] T004 Implementar os modelos estruturados de dados e respostas em `src/tools/gastos_tools.py`.
- [x] T005 Escrever teste para o resolvedor de dados `_resolve_ceap_dataset` (validação de `casa`, normalização de nomes de colunas e suporte a partições por ano).
- [x] T006 Implementar `_resolve_ceap_dataset` em `src/tools/gastos_tools.py` utilizando Polars `scan_parquet` e/ou DuckDB.

---

## Phase 3: User Story 1 - `get_top_ceap_spender` (Priority: P1) 🎯 MVP

**Objetivo**: Consultar os maiores gastadores da cota parlamentar (Golden Dataset ID 1).

- [x] T007 [TDD-Red] Escrever testes unitários para `get_top_ceap_spender`:
  - Teste com dados da Câmara retornando o ranking correto (`posicao=1`, parlamentar com maior soma de `vlrLiquido`).
  - Teste com dados do Senado para múltiplos gastadores (`top_n=3`).
  - Teste para ano inexistente retornando lista vazia sem quebrar.
  - Teste com validação de `casa` inválida levantando `ValueError`.
- [x] T008 [TDD-Green] Implementar a função `get_top_ceap_spender(casa, ano, top_n=1, base_dir=None)` em `src/tools/gastos_tools.py` para fazer todos os testes de T007 passarem.
- [x] T009 [Refactor] Refatorar agregação garantindo modo `read_only=True` e tipagem estrita de saída.

---

## Phase 4: User Story 2 - `list_expense_categories` (Priority: P1)

**Objetivo**: Listar categorias empíricas de despesa e verificar ocorrência real (Golden Dataset IDs 2, 11, 16, 17, 22).

- [x] T010 [TDD-Red] Escrever testes unitários para `list_expense_categories`:
  - Teste na base do Senado confirmando categoria de consultorias/assessorias com exemplos de fornecedores (ID 2).
  - Teste na base da Câmara confirmando categorias de alimentação e passagens aéreas (IDs 11 e 17).
  - Teste para a flag `incluir_exemplos=False`.
  - Teste para verificação de ausência de categoria ("aquisição de imóveis" ou "gastos eleitorais" retornando que não constam).
- [x] T011 [TDD-Green] Implementar a função `list_expense_categories(casa, incluir_exemplos=True, base_dir=None)` em `src/tools/gastos_tools.py` até a suíte passar.
- [x] T012 [Refactor] Otimizar agregação de exemplos e normalização de descrições.

---

## Phase 5: User Story 3 - `check_parliamentary_expenses` (Priority: P2)

**Objetivo**: Auditar despesas com filtros e cálculo de agregados numéricos (Golden Dataset ID 13).

- [x] T013 [TDD-Red] Escrever testes unitários para `check_parliamentary_expenses`:
  - Teste com filtro por categoria `"combustivel"` verificando cálculo correto de `valor_min`, `valor_max`, `valor_medio` e `qtd_lancamentos` (ID 13).
  - Teste com filtro de `parlamentar_id` isolando os gastos de um deputado específico.
  - Teste para categoria inexistente retornando agregações zeradas e `qtd_lancamentos=0`.
- [x] T014 [TDD-Green] Implementar `check_parliamentary_expenses(casa, ano, categoria=None, parlamentar_id=None, limite_amostra=5, base_dir=None)` em `src/tools/gastos_tools.py`.
- [x] T015 [Refactor] Garantir tratamento seguro contra valores nulos e suporte a buscas parciais case-insensitive na categoria.

---

## Phase 6: Exportação, Integração e Validação do Golden Dataset

- [x] T016 Exportar as tools e modelos em `src/tools/__init__.py`.
- [x] T017 Executar a suíte completa de testes com `pytest tests/test_gastos_tools.py -v`.
- [x] T018 Adicionar testes de ponta a ponta simulando as claims 1, 2, 11, 13, 16, 17 e 22 do Golden Dataset contra as tools implementadas.
