# Feature Specification: Tools do Grupo de Gastos (CEAP e CEAPS)

**Feature Branch**: `001-tools-gastos`  
**Created**: 2026-10-01  
**Status**: Specified  
**Input**: "Implementar tools do grupo de gastos CEAP e CEAPS: get_top_ceap_spender, list_expense_categories e check_parliamentary_expenses"

---

## 1. Visão Geral & Contexto

Esta funcionalidade implementa as ferramentas analíticas do **Grupo de Gastos** (Seção 3 de `docs/tools_specification.md`) no sistema multiagente de fact-checking político. As tools operam **exclusivamente sobre dados locais já ingeridos** (arquivos Parquet em `data/processed/camara/ceap` e `data/processed/senado/ceaps`) por meio de consultas analíticas com DuckDB (`read_only=True`) e/ou Polars, sem nenhuma chamada de rede externa durante a execução.

Estas ferramentas respondem diretamente a reivindicações de gastos parlamentares no `golden_dataset_v1.json`, abrangendo:
* **Ranking e superlativos de despesas** (Claim ID 1)
* **Verificação empírica de categorias de despesas executadas** (Claim IDs 2, 11, 16, 17, 22)
* **Auditoria de limites, tetos e valores atípicos** (Claim ID 13)

---

## 2. Princípios Constitucionais Aplicáveis

Conforme estabelecido na Constituição do Projeto (`.specify/memory/constitution.md`):
* **Princípio I (Veredito Estritamente Baseado em Evidência Rastreável):** As tools devem retornar estruturas ricas com metadados da fonte (tabela, ano, agregados) para que o Agente Sintetizador possa citar os valores exatos.
* **Princípio IV (Separação entre Dado Transacional e Regra Institucional):** As tools de gastos relatam **fatos transacionais auditados** (o que foi pago/reembolsado). Elas NÃO julgam sozinhas se uma despesa é legal ou regimental; isso é delegado à base normativa (`check_institutional_rule`).
* **Princípio V (Golden Dataset como Portão de Aceite Absoluto):** A implementação deve cobrir os casos de teste derivados dos IDs 1, 2, 11, 13, 16, 17 e 22.
* **Princípio VII (TDD Inegociável):** Testes unitários com dados mockados em `tests/test_gastos_tools.py` devem preceder e guiar toda a implementação do módulo `src/tools/gastos_tools.py`.
* **Princípio VIII (Isolamento e Cobertura Unitária Rigorosa):** Cada tool deve funcionar isoladamente e possuir fixtures controladas sem depender da existência prévia de gigabytes de dados reais no ambiente de CI/teste.

---

## 3. User Scenarios & Testing (Histórias Priorizadas)

### User Story 1 - Ranking de Gastos da Cota Parlamentar (Priority: P1)

Como **Agente Roteador de Fact-Checking**,  
Quero consultar os maiores gastadores da Cota Parlamentar (CEAP/CEAPS) para um ano específico e casa legislativa,  
Para verificar alegações sobre quem liderou os gastos ou verificar o valor total despendido por parlamentares de destaque (atendendo ao Golden Dataset ID 1).

**Por que esta prioridade:** É a ferramenta básica para checagens de superlativos ("quem mais gastou", "foi o deputado X que liderou os gastos"), necessária para validar o caso ID 1 do Golden Dataset.

**Teste Independente:** Pode ser testado com um dataset mock de CEAP contendo 3 deputados com valores distintos; a função deve retornar o topo do ranking na ordem correta com formatação canônica.

**Cenários de Aceite:**
1. **Given** dados de CEAP da Câmara para o ano 2023,  
   **When** `get_top_ceap_spender(casa="camara", ano=2023, top_n=1)` é invocado,  
   **Then** o sistema retorna uma lista contendo exatamente 1 registro com o maior valor agregado (`vlrLiquido`), incluindo nome do parlamentar, UF, partido, valor total e posição no ranking (`posicao=1`).
2. **Given** uma solicitação para os top 5 senadores em 2022,  
   **When** `get_top_ceap_spender(casa="senado", ano=2022, top_n=5)` é invocado,  
   **Then** o sistema retorna até 5 registros ordenados decrescentemente por valor total.
3. **Given** um ano sem nenhum registro de despesa,  
   **When** `get_top_ceap_spender(casa="camara", ano=1990, top_n=1)` é invocado,  
   **Then** o sistema retorna uma lista vazia `[]` sem levantar exceção não tratada.

---

### User Story 2 - Consulta Empírica de Categorias de Despesas (Priority: P1)

Como **Agente Roteador / Sintetizador de Fact-Checking**,  
Quero listar as categorias de despesas efetivamente reembolsadas na Câmara ou no Senado, com contagem e exemplos de lançamentos,  
Para provar ou refutar se uma determinada categoria é utilizada na prática institucional (atendendo aos Golden Dataset IDs 2, 11, 16, 17, 22).

**Por que esta prioridade:** Responde a múltiplos casos do Golden Dataset onde a alegação afirma que a cota cobre (ou foi proibida de cobrir) certos tipos de despesas (ex.: alimentação, consultorias, passagens aéreas). A presença de lançamentos históricos comprova empiricamente a utilização.

**Teste Independente:** Execução sobre arquivo com múltiplas categorias de despesa; validação de que retorna a lista agregada com volume, contagem e exemplos de fornecedores.

**Cenários de Aceite:**
1. **Given** a base de dados do Senado Federal (CEAPS),  
   **When** `list_expense_categories(casa="senado", incluir_exemplos=True)` é invocado,  
   **Then** o retorno inclui a categoria de consultoria/assessoria técnica com contagem de lançamentos > 0 e exemplos de fornecedores (atendendo à evidência factual do ID 2).
2. **Given** a base da Câmara dos Deputados (CEAP),  
   **When** `list_expense_categories(casa="camara", incluir_exemplos=True)` é invocado,  
   **Then** o retorno inclui categorias de alimentação e passagens aéreas com contagens e valores totais consolidados (atendendo aos IDs 11 e 17).
3. **Given** a flag `incluir_exemplos=False`,  
   **When** a tool for chamada,  
   **Then** a lista de categorias é retornada com `exemplos=[]`, otimizando o payload de resposta.

---

### User Story 3 - Auditoria Parametrizada de Lançamentos de Despesa (Priority: P2)

Como **Agente Roteador de Fact-Checking**,  
Quero consultar e agregar lançamentos de despesa com filtros por parlamentar, categoria e ano, obtendo métricas de mínimo, máximo, média e contagem,  
Para refutar alegações sobre tetos inventados ou limites incorretos de gastos (atendendo ao Golden Dataset ID 13).

**Por que esta prioridade:** Permite auditar quantitativamente lançamentos reais para confrontar valores numéricos alegados (ex.: alegação de teto fixo de R$ 500/ano em combustível desmentida por despesas de valores superiores).

**Teste Independente:** Consulta com filtro de categoria `combustível` para o ano 2026/2023; verificação de que `valor_max` e lançamentos amostrais refletem com exatidão a agregação de `vlrLiquido`.

**Cenários de Aceite:**
1. **Given** registros de combustível na CEAP para a Câmara,  
   **When** `check_parliamentary_expenses(casa="camara", ano=2023, categoria="combustivel")` é invocado,  
   **Then** o sistema retorna `{filtros_aplicados, valor_min, valor_max, valor_medio, qtd_lancamentos, amostra}` onde `valor_max` expõe o maior lançamento do período.
2. **Given** um `parlamentar_id` específico resolvido previamente,  
   **When** a consulta for filtrada por esse ID,  
   **Then** apenas despesas daquele parlamentar são consideradas na agregação.
3. **Given** uma categoria inexistente nos registros,  
   **When** a tool for invocada,  
   **Then** o sistema retorna `qtd_lancamentos=0`, `amostra=[]`, `valor_min=0.0`, `valor_max=0.0`, `valor_medio=0.0` sem falhar.

---

## 4. Requisitos de Sistema

### Requisitos Funcionais

- **FR-001**: O sistema DEVE fornecer a função `get_top_ceap_spender(casa: str, ano: int, top_n: int = 1) -> List[TopSpenderResult]` em `src/tools/gastos_tools.py`.
- **FR-002**: O sistema DEVE fornecer a função `list_expense_categories(casa: str, incluir_exemplos: bool = True) -> List[ExpenseCategoryResult]` em `src/tools/gastos_tools.py`.
- **FR-003**: O sistema DEVE fornecer a função `check_parliamentary_expenses(casa: str, ano: int, categoria: Optional[str] = None, parlamentar_id: Optional[str] = None, limite_amostra: int = 5) -> ExpenseAuditResult` em `src/tools/gastos_tools.py`.
- **FR-004**: Todas as entradas e saídas DEVEM ser tipadas e validadas através de modelos Pydantic com serialização amigável a JSON/Dicionários.
- **FR-005**: A resolução de caminhos dos arquivos Parquet DEVE suportar tanto o layout particionado oficial (`data/processed/<casa>/ceap/ano=<ano>/*.parquet`) quanto views em memória para execução de testes unitários.
- **FR-006**: Os parâmetros de texto (como `casa` e `categoria`) DEVEM sofrer normalização (remoção de espaços excedentes, caixa baixa, remoção de acentos para busca flexível de categoria).
- **FR-007**: A execução NÃO PODE realizar qualquer requisição HTTP ou acesso de rede externa.

### Requisitos Não-Funcionais

- **NFR-001 (Performance):** Consultas analíticas locais sobre partições de um único ano devem responder em menos de 300ms.
- **NFR-002 (Integridade & Concorrência):** O acesso aos arquivos DuckDB / Parquet deve ser estritamente em modo leitura (`read_only=True`), permitindo consultas paralelas sem locks de escrita.
- **NFR-003 (Robustez):** Erros de diretório inexistente ou arquivos corrompidos devem ser capturados e convertidos em retornos estruturados com mensagens descritivas de log sem quebrar a execução do agente.
- **NFR-004 (TDD):** 100% das funções do módulo devem ser cobertas por testes unitários em `tests/test_gastos_tools.py`.

---

## 5. Mapeamento com o Golden Dataset

| ID Golden | Reivindicação | Tool de Gastos Utilizada | Evidência Fornecida pela Tool |
|---|---|---|---|
| **1** | *"Em 2023, o deputado que mais gastou a cota parlamentar (CEAP) foi Pompeo de Mattos (PDT-RS)."* | `get_top_ceap_spender(casa="camara", ano=2023, top_n=1)` | Confirmação do parlamentar no topo do ranking com valor acumulado. |
| **2** | *"Senadores podem usar a verba indenizatória (CEAPS) para pagar consultorias e assessorias técnicas para o mandato."* | `list_expense_categories(casa="senado")` | Evidência empírica de lançamentos reais sob a rubrica de consultoria. |
| **11** | *"Deputados podem pedir reembolso de gastos com alimentação usando a cota parlamentar."* | `list_expense_categories(casa="camara")` | Evidência empírica da categoria de alimentação na CEAP. |
| **13** | *"Todo deputado federal tem um teto fixo de R$ 500,00 por ano para gastar com combustível pela cota parlamentar."* | `check_parliamentary_expenses(casa="camara", ano=2023, categoria="combustivel")` | Refutação numérica mostrando despesas individuais e agregadas substancialmente maiores que R$ 500. |
| **16** | *"Um deputado pode usar a cota parlamentar para comprar um imóvel em seu próprio nome."* | `list_expense_categories(casa="camara")` | Ausência da categoria "aquisição de imóveis" na base empírica da CEAP (complementada por `check_institutional_rule`). |
| **17** | *"O Senado proibiu totalmente o uso da cota de gastos (CEAPS) para pagar passagens aéreas."* | `list_expense_categories(casa="senado")` | Comprovação empírica de lançamentos contínuos de passagens aéreas na CEAPS. |
| **22** | *"Um senador pode usar a cota parlamentar para pagar os gastos da própria campanha eleitoral."* | `list_expense_categories(casa="senado")` | Ausência de categoria de gastos eleitorais na cota de exercício parlamentar. |

---

## 6. Tratamento de Casos de Borda (Edge Cases)

1. **Casa legislativa desconhecida:** Se `casa` for diferente de `"camara"` ou `"senado"`, a tool deve levantar `ValueError` informativo ("Casa inválida. Valores aceitos: 'camara', 'senado'").
2. **Dados ausentes para determinado ano:** Se a partição `ano=XXXX` não existir em disco, a tool retorna resultado vazio (ex: lista vazia ou agregações zeradas), sem exceção não tratada.
3. **Valores negativos / estornos:** Na CEAP/CEAPS ocorrem valores negativos decorrentes de devolução/estorno de bilhetes ou cancelamentos. O cálculo de soma (`sum(vlrLiquido)`) deve considerar o valor líquido real conforme a regra contábil da cota.
4. **Fuzzy match em categoria:** Busca de categoria deve aceitar substrings parciais insensíveis a acentos e maiúsculas (ex: `"combustivel"` encontra `"COMBUSTÍVEIS E LUBRIFICANTES"`).
