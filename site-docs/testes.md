# Testes

## Filosofia TDD

O projeto segue **Test-Driven Development (TDD)** como regra **inegociável** (Princípio VII do [`AGENTS.md`](https://github.com/yanrdgs-dev/challenge1-grupo13/blob/main/AGENTS.md)):

!!! warning "Ciclo obrigatório"
    ```
    🔴 Escrever o teste falhando
         ↓
    🟢 Implementar o mínimo para passar
         ↓
    🔵 Refatorar
    ```
    Pull requests que adicionam código sem teste correspondente **anterior** são rejeitados.

---

## Executar a suíte completa

```bash
uv run pytest                    # todos os testes
uv run pytest -v                 # modo verboso (um teste por linha)
uv run pytest tests/test_gastos_tools.py  # módulo específico
uv run pytest -k "tse"           # filtra por nome
```

---

## Inventário de testes (branch `main`)

| Arquivo de Teste | Módulo Testado | Testes | Status |
|---|---|---|---|
| `test_build_parquet.py` | `src/etl/build_parquet.py` | 19 | ✅ |
| `test_build_dim_politicos.py` | `src/etl/build_dim_politicos.py` | 6 | ✅ |
| `test_duckdb_queries.py` | `src/database/duckdb_client.py` | 10 | ✅ |
| `test_llm_client.py` | `src/core/llm_client.py` | 12 | ✅ |
| `test_normalizer.py` | `src/tools/normalizer.py` | 7 | ✅ |
| `test_resolve_politician.py` | `src/tools/resolve_politician.py` | 20 | ⚠️ parcial* |
| `test_resolve_proposition.py` | `src/tools/resolve_proposition.py` | 10 | ✅ |
| `test_legislative_client.py` | `src/tools/legislative_client.py` | 7 | ✅ |
| `test_legislativo_tools.py` | `src/tools/legislativo_tools.py` | 12 | ✅ |
| `test_gastos_tools.py` | `src/tools/gastos_tools.py` | 15 | ✅ |
| `test_votacoes_tools.py` | `src/tools/votacoes_api.py` | 17 | ✅ |
| `test_knowledge_tools.py` | `src/tools/knowledge_tools.py` | 14 | ✅ |
| `test_extractors.py` | `src/ingestion/extractors.py` | 7 | ✅ |
| `test_url_scraper.py` | `src/services/url_scraper.py` | 9 | ✅ |

> \* `test_resolve_politician.py` possui testes que dependem do Parquet `dim_politicos.parquet` ainda não gerado localmente. Os testes de mock passam; os de integração falham sem o dado.

---

## Regras obrigatórias por tool

Toda tool do catálogo precisa de suíte cobrindo **no mínimo**:

- [x] **Caminho feliz** — entidade resolvida, dado encontrado
- [x] **Entidade não encontrada** — retorno estruturado sem exceção
- [x] **Entidade ambígua** — `ambiguous: True` com alternativas (quando aplicável)
- [x] **Erro de rede simulado** — `timeout` e `ConnectionError` via mock (sem chamada real de API)

---

## Garantias de isolamento

!!! note "100% mockado para tools que chamam APIs"
    Todos os testes de tools que acessam APIs externas (Câmara, Senado) usam `unittest.mock.patch` para interceptar chamadas HTTP. Nenhuma chamada real é feita durante `pytest`.

```python
# Exemplo de mock correto
with patch("src.tools.http_client.requests.get", return_value=mock_response):
    resultado = get_proposition_vote_result(casa="camara", id_proposicao="2256735")
    assert resultado["resultado"] == "Aprovado"
```

---

## Commits de teste (padrão Conventional Commits)

Commits de testes que **antecedem** a implementação (ciclo TDD) usam o prefixo `test:` mesmo quando o código ainda não existe:

```bash
git commit -m "test(scraper): adiciona suite de testes unitarios para url_scraper"
git commit -m "feat(scraper): implementa extracao de artigos via trafilatura"
```
