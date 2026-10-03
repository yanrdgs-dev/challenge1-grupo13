# Quickstart & Guia de Validação: `resolve_politician`

**Feature**: `001-resolve-politician`  
**Data**: 2026-10-01  
**Status**: Concluído  

---

## 1. Pré-Requisitos

1. **Ambiente Python**:
   - Python 3.11+ com o ambiente virtual configurado (`.venv`).
   - Dependências essenciais instaladas: `duckdb`, `polars`, `pyarrow`, `rapidfuzz`, `pytest`.
2. **Dados Processados**:
   - Existência dos arquivos Parquet locais em `data/processed/camara/`, `data/processed/senado/` e `data/processed/tse/`.
   - Tabela dimensional unificada em `data/processed/dim_politicos.parquet`.

---

## 2. Configuração e Inicialização

Caso `dim_politicos.parquet` ainda não esteja materializada na base de dados local, executar o utilitário de geração:

```bash
.venv/bin/python -m src.etl.build_dim_politicos
```

---

## 3. Cenários de Validação Ponta a Ponta

### Cenário 1: Resolução Direta de Deputado Inequívoco (Caminho Feliz - Caso do Golden Dataset)
- **Objetivo:** Resolver parlamentar citado na Claim 1 do Golden Dataset (`"Pompeo de Mattos"`).
- **Invocação:**
  ```python
  from src.tools.resolve_politician import resolve_politician

  result = resolve_politician(nome_busca="Pompeo de Mattos", uf="RS")
  print(result)
  ```
- **Resultado Esperado:**
  - `ambiguous`: `False`
  - `ideCadastro`: `73485` (ou respectivo ID oficial na Câmara)
  - `nome_civil`: Contendo `"POMPEO DE MATTOS"`
  - `uf`: `"RS"`
  - `partido`: `"PDT"`
  - `candidatos_alternativos`: `[]`

---

### Cenário 2: Resolução com Variação Ortográfica e Ausência de Acentos
- **Objetivo:** Validar resiliência do algoritmo a nomes digitados em minúsculas e sem acentuação (`"tabata amaral"`).
- **Invocação:**
  ```python
  result = resolve_politician(nome_busca="tabata amaral")
  ```
- **Resultado Esperado:**
  - `ambiguous`: `False`
  - `nome_civil`: `"TABATA CLAUDIA AMARAL DE PONTES"`
  - `uf`: `"SP"`
  - `match_score`: $\ge 90.0$

---

### Cenário 3: Detecção de Homônimo / Ambiguidade Sem Filtro de UF
- **Objetivo:** Consultar nome comum sem especificar estado e verificar retorno de ambiguidade com alternativas.
- **Invocação:**
  ```python
  result = resolve_politician(nome_busca="Marcelo")
  ```
- **Resultado Esperado:**
  - `ambiguous`: `True`
  - `ideCadastro`: `None`
  - `candidatos_alternativos`: Lista não vazia contendo os registros de candidatos homônimos encontrados.

---

### Cenário 4: Desambiguação de Homônimo via Parâmetro de UF
- **Objetivo:** Reexecutar a consulta ambígua fornecendo a UF discriminadora.
- **Invocação:**
  ```python
  result = resolve_politician(nome_busca="Marcelo Freixo", uf="RJ")
  ```
- **Resultado Esperado:**
  - `ambiguous`: `False`
  - `uf`: `"RJ"`
  - `candidatos_alternativos`: `[]`

---

### Cenário 5: Personalidade Não Encontrada / Sem Mandato Federal
- **Objetivo:** Garantir retorno estruturado de "não encontrado" sem inventar IDs ou forçar casamentos espúrios (Princípio III da Constituição).
- **Invocação:**
  ```python
  result = resolve_politician(nome_busca="Cidadão Inexistente da Silva Sauro")
  ```
- **Resultado Esperado:**
  - `ambiguous`: `False`
  - `ideCadastro`: `None`
  - `sq_candidato`: `None`
  - `candidatos_alternativos`: `[]`
  - `match_score`: `None`

---

## 4. Execução da Suíte de Testes Automatizados

Conforme o Princípio VII (TDD) e VIII (Isolamento de Testes) da Constituição, execute a suíte de testes com cobertura completa dos quatro quadrantes:

```bash
.venv/bin/pytest tests/test_resolve_politician.py -v
```

Verifique se 100% dos testes passam de forma estritamente offline (sem efetuar requisições de rede).
