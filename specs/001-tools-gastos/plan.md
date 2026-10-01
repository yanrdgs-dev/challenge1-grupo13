# Implementation Plan: Tools do Grupo de Gastos (CEAP e CEAPS)

**Branch**: `001-tools-gastos` | **Date**: 2026-10-01 | **Spec**: [specs/001-tools-gastos/spec.md](file:///Users/aluno2/Documents/Residencia/projeto_fakenews/challenge1-grupo13/specs/001-tools-gastos/spec.md)  
**Input**: Feature specification from `specs/001-tools-gastos/spec.md` (Seção 3 de `docs/tools_specification.md`)

---

## 1. Summary

Implementação do catálogo analítico de ferramentas de **Gastos Parlamentares** (`get_top_ceap_spender`, `list_expense_categories`, `check_parliamentary_expenses`) para viabilizar a verificação empírica de despesas com a Cota para o Exercício da Atividade Parlamentar da Câmara (CEAP) e da Verba Indenizatória do Senado (CEAPS). A execução é 100% local, consultando partições Parquet existentes via DuckDB em modo somente leitura (`DuckDBClient(read_only=True)`) e Polars LazyFrames, sem chamadas de rede externa.

---

## 2. Technical Context

* **Linguagem & Runtime**: Python 3.11+ (compatível com 3.14)
* **Dependências Principais**: `polars >= 0.20`, `duckdb >= 0.10`, `pydantic >= 2.0`, `pytest >= 8.0`
* **Armazenamento de Dados**: Parquet particionado em disco (`data/processed/camara/ceap/ano=<ano>/*.parquet` e `data/processed/senado/ceaps/ano=<ano>/*.parquet`)
* **Testes & Qualidade**: `pytest` com fixtures sintéticas temporárias (`tmp_path`) e DuckDB in-memory (`:memory:`)
* **Restrições de Desempenho**: Tempo de resposta analítica < 300ms por execução; Zero overhead de rede; Nenhum bloqueio de escrita (read-only garantido).
* **Conformidade Constitucional**: Respeito estrito aos 10 princípios de `.specify/memory/constitution.md` (especialmente TDD, neutralidade e evidência auditável).

---

## 3. Constitution Check (Gates de Aceite)

| Princípio Constitucional | Status | Validação no Design |
|---|---|---|
| **I. Evidência Rastreável** | PASS | Retornos incluem agregados numéricos, contagens e metadados de fonte para citação no sintetizador. |
| **IV. Dado Transacional vs. Regra** | PASS | Tools focam apenas em "o que foi lançado nos dados", sem emitir parecer de legalidade subjetiva. |
| **V. Golden Dataset Gate** | PASS | Casos de teste mapeiam com exatidão os IDs 1, 2, 11, 13, 16, 17 e 22 do `golden_dataset_v1.json`. |
| **VII. TDD Inegociável** | PASS | Criação mandatória de `tests/test_gastos_tools.py` antes da implementação em `src/tools/gastos_tools.py`. |
| **VIII. Isolamento Unitário** | PASS | Cada teste utiliza dados simulados em memória sem acoplamento a pipelines externos ou downloads de rede. |
| **X. Stack Python Unificada** | PASS | Adoção estrita de Polars, DuckDB e Pydantic. |

---

## 4. Project Structure & Arquivos Envolvidos

```text
challenge1-grupo13/
├── specs/001-tools-gastos/
│   ├── spec.md                   # Especificação de requisitos e cenários
│   ├── plan.md                   # Este plano arquitetural
│   └── tasks.md                  # Checklist sequencial TDD
├── src/
│   └── tools/
│       ├── __init__.py           # Exportação das tools e schemas de gastos
│       └── gastos_tools.py       # Implementação das 3 tools e modelos Pydantic
└── tests/
    └── test_gastos_tools.py      # Suíte TDD cobrindo cenários e casos de borda
```

---

## 5. Contratos de Dados & Modelos Pydantic

### 5.1 `get_top_ceap_spender`
```python
class TopSpenderItem(BaseModel):
    posicao: int
    nome_parlamentar: str
    uf: str
    partido: str
    valor_total: float
    id_parlamentar: Optional[str] = None

class TopSpenderResponse(BaseModel):
    casa: str
    ano: int
    top_n: int
    gastadores: List[TopSpenderItem]
    total_parlamentares_analisados: int
```

### 5.2 `list_expense_categories`
```python
class ExpenseCategoryItem(BaseModel):
    categoria: str
    qtd_lancamentos: int
    valor_total: float
    exemplos: List[Dict[str, Any]] = []

class ExpenseCategoriesResponse(BaseModel):
    casa: str
    total_categorias: int
    categorias: List[ExpenseCategoryItem]
```

### 5.3 `check_parliamentary_expenses`
```python
class ExpenseAuditResult(BaseModel):
    casa: str
    ano: int
    filtros_aplicados: Dict[str, Any]
    qtd_lancamentos: int
    valor_min: float
    valor_max: float
    valor_medio: float
    valor_total: float
    amostra: List[Dict[str, Any]]
```

---

## 6. Estratégia de Implementação Analítica

1. **Localização de Arquivos e Fallback Seguro:**
   - Criação de função auxiliar `_resolve_ceap_dataset(casa: str, ano: Optional[int] = None, base_dir: Optional[Path] = None) -> Union[pl.LazyFrame, Path]`
   - Suporte ao parâmetro opcional `base_dir` nas tools para permitir injeção de dependência direta pelas fixtures de teste (`tmp_path`).
   - Mapeamento de colunas canônicas entre Câmara (`txNomeParlamentar`, `sgUF`, `sgPartido`, `txtDescricao`, `vlrLiquido`) e Senado (`SENADOR`, `UF`, `PARTIDO`, `TIPO_DESPESA`, `VALOR_REEMBOLSADO`).

2. **Consultas Analíticas Polars/DuckDB:**
   - `get_top_ceap_spender`: `group_by([nome, uf, partido]).agg(pl.col(vlr).sum()).sort(desc).head(top_n)`
   - `list_expense_categories`: `group_by(categoria).agg(count(), sum(vlr), slice_sample(fornecedor, vlr)).sort(count.desc())`
   - `check_parliamentary_expenses`: `filter(ano == X, categoria.contains(Y), id == Z).agg(min, max, mean, count, sum)`

3. **Validação e Normalização de Entradas:**
   - `casa.strip().lower()` com validação em `{"camara", "senado"}`.
   - Tratamento de categorias com busca flexível (unidecode / normalização unicode) para tolerar variações como "combustivel" vs "COMBUSTÍVEIS E LUBRIFICANTES".
