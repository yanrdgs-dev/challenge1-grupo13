# Golden Dataset v1

## O que é?

O **Golden Dataset v1** é o conjunto de referência (*ground truth*) do sistema. Contém **30 alegações políticas verificáveis** usadas como portão de aceite para validação do pipeline completo.

**Arquivo:** [`golden_dataset_v1.json`](https://github.com/yanrdgs-dev/challenge1-grupo13/blob/main/golden_dataset_v1.json)

---

## Distribuição dos vereditos

| Veredito | Quantidade | Proporção |
|---|---|---|
| ✅ VERDADEIRO | 12 | 40% |
| ❌ FALSO | 12 | 40% |
| ⚠️ INCONCLUSIVO | 6 | 20% |
| **Total** | **30** | **100%** |

---

## Resultado do benchmark (v1)

O pipeline foi executado de ponta a ponta contra as 30 alegações:

| Categoria | Total | Acertos | Acurácia |
|---|---|---|---|
| GASTOS | 18 | 18 | **100%** ✅ |
| VOTAÇÕES | 12 | 10 | **83%** ✅ |
| **Geral** | **30** | **28** | **93,3%** ✅ |

!!! success "Meta atingida"
    O critério de aceite definido na Issue [#22](https://github.com/yanrdgs-dev/challenge1-grupo13/issues/22) exigia acurácia global ≥ 80%. O sistema atingiu **93,3%**.

---

## Estrutura de cada caso

```json
{
    "id": 1,
    "claim": "Em 2023, o deputado que mais gastou a cota parlamentar (CEAP) foi Pompeo de Mattos (PDT-RS).",
    "expected_verdict": "VERDADEIRO",
    "category": "GASTOS",
    "target_entity": "Pompeo de Mattos"
}
```

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | `int` | Identificador único do caso |
| `claim` | `str` | Alegação em linguagem natural |
| `expected_verdict` | `str` | `"VERDADEIRO"` \| `"FALSO"` \| `"INCONCLUSIVO"` |
| `category` | `str` | `"GASTOS"` \| `"VOTACOES"` |
| `target_entity` | `str` | Nome do parlamentar ou proposição alvo |

---

## Exemplos de alegações por veredito

=== "VERDADEIRO"

    - *"Em 2023, o deputado que mais gastou a cota parlamentar (CEAP) foi Pompeo de Mattos (PDT-RS)."*
    - *"Senadores podem usar a verba indenizatória (CEAPS) para pagar consultorias e assessorias."*
    - *"A aprovação de indicados a ministro do STF pelo Senado é feita por votação secreta."*

=== "FALSO"

    - *"A votação da PEC 45/2019 (Reforma Tributária) foi aprovada por unanimidade no Senado."*
    - *"Deputados têm um limite fixo de R$ 500 anuais para gastos com combustível na CEAP."*

=== "INCONCLUSIVO"

    - *"Um deputado gastou muito dinheiro recentemente com passagens aéreas."*
    - *"Segundo comentários na internet, um senador votou contra a reforma."*

---

## Como executar o benchmark

```bash
# Executar o benchmark completo (requer LLM ativo)
uv run python scripts/run_benchmark.py

# Resultado salvo em:
# benchmark_results_golden_v1.json
```

---

## Regras de aceite para novas alegações

Qualquer nova alegação adicionada ao Golden Dataset deve:

- [x] Ter veredito verificável contra dado público oficial
- [x] Nomear uma entidade resolvível (parlamentar + UF ou proposição numerada)
- [x] Citar um evento ancorado no tempo (ano eleitoral, legislatura, data)
- [x] Ter cobertura de tool correspondente **antes** de ser adicionada
- [x] Passar por revisão de neutralidade pelo Product Owner
