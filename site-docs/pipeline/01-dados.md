# Etapa 1 — Mapeamento de Dados e Esquemas Oficiais

## Objetivo

Identificar, documentar e selecionar estritamente os atributos necessários das bases de dados oficiais do **TSE** (Tribunal Superior Eleitoral) e da **Câmara dos Deputados** para cobrir os pilares de fact-checking do MVP.

**Issue:** [#2 — 1.1 Mapeamento de Esquemas](https://github.com/yanrdgs-dev/challenge1-grupo13/issues/2) ✅

---

## Fontes de dados oficiais

=== "TSE — Dados Eleitorais"

    - `consulta_cand_{ANO}_{UF}.csv` — Cadastro de Candidatos
    - `despesas_pagas_candidatos_{ANO}_{UF}.csv` — Prestação de Contas (Despesas Pagas)
    - `bem_candidato_{ANO}_{UF}.csv` — Declaração de Bens

    **Encoding:** `latin1 (ISO-8859-1)` | **Separador:** `;` (ponto e vírgula)

=== "Câmara dos Deputados"

    - API Dados Abertos: `https://dadosabertos.camara.leg.br/api/v2/`
    - Votações nominais por proposição
    - Cota Parlamentar (CEAP) — Portal da Transparência
    - Proposições e ementas legislativas

=== "Senado Federal"

    - API Dados Abertos: `https://legis.senado.leg.br/dadosabertos/`
    - Matérias legislativas atualizadas
    - Cota Parlamentar do Senado (CEAPS)

---

## Esquemas selecionados

!!! tip "Critério de poda"
    Foram mantidas apenas as colunas estritamente necessárias para fact-checking. A poda estrutural reduz o volume de dados em disco em **≥ 70%** em relação aos CSVs brutos.

### TSE — Despesas de Campanha

```python
TSE_DESPESAS_COLUMNS = [
    "ANO_ELEICAO",
    "SG_UF",
    "SQ_CANDIDATO",
    "NM_CANDIDATO",
    "NM_URNA_CANDIDATO",
    "SG_PARTIDO",
    "DS_CARGO",
    "VR_PAGTO_DESPESA",     # Float64 (vírgula → ponto)
    # Opcionais para contexto:
    "DS_TIPO_DESPESA",
    "NM_FORNECEDOR",
]
```

### TSE — Declaração de Bens

```python
TSE_BENS_COLUMNS = [
    "ANO_ELEICAO",
    "SG_UF",
    "SQ_CANDIDATO",
    "DS_TIPO_BEM_CANDIDATO",
    "DS_BEM_CANDIDATO",
    "VR_BEM_CANDIDATO",
]
```

### Câmara — Votações Nominais

```python
CAMARA_VOTACOES_COLUMNS = [
    "idVotacao",
    "data",
    "idDeputado",
    "nomeDeputado",
    "siglaPartido",
    "siglaUf",
    "voto",          # Sim / Não / Abstenção / Obstrução
]
```

### Câmara — Cota Parlamentar (CEAP)

```python
CEAP_COLUMNS = [
    "nuDeputadoId",
    "txNomeParlamentar",
    "sgPartido",
    "sgUF",
    "numAno",
    "numMes",
    "txtDescricao",        # Categoria de gasto
    "txtFornecedor",
    "vlrLiquido",
]
```

---

## Localização dos arquivos

| Artefato | Caminho |
|---|---|
| Documento de esquemas | [`docs/data_schemas.md`](https://github.com/yanrdgs-dev/challenge1-grupo13/blob/main/docs/data_schemas.md) |
| Código dos esquemas | [`src/schemas/data_schemas.py`](https://github.com/yanrdgs-dev/challenge1-grupo13/blob/main/src/schemas/data_schemas.py) |
| Dados processados | `data/processed/` (não versionado, gerado pelo ETL) |
