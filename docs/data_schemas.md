# Mapeamento de Esquemas e Seleção de Atributos Oficiais

- **Documento:** `docs/data_schemas.md`
- **Projeto:** Verificação de Fake News Política & Desinformação (CBL - Grupo 13)
- **Sprint:** Sprint 1 (Task 1.1)
- **Status:** Proposto para Validação do P.O.

---

## 1. Visão Geral e Racional Técnico

Os conjuntos de dados brutos fornecidos pelo **TSE** (Repositório de Dados Eleitorais) e pela **Câmara dos Deputados** (Portal e API de Dados Abertos) contêm dezenas de colunas, totalizando dezenas de gigabytes de dados redundantes quando ingeridos sem filtragem (e.g., repetições de descrições textuais, dados de protocolo interno, metadados de upload e links de mídia).

Para atingir **latência analítica em milissegundos** via **DuckDB** e **Polars** com redução $\ge 70\%$ do volume em disco, este documento formaliza a poda estrutural (*pruning* de colunas), selecionando estritamente os atributos necessários para cobrir os principais pilares de fact-checking político do MVP:
1. **Auditoria de Gastos Eleitorais (TSE)**: Totalização e conferência de despesas declaradas por candidato, cargo, UF e ano eleitoral.
2. **Patrimônio Declarado de Candidatos (TSE)**: Levantamento de bens juramentados de candidatos para verificação de enriquecimento e desinformação patrimonial.
3. **Checagem de Votações Nominais (Câmara)**: Verificação do posicionamento e voto individual de deputados em matérias legislativas relevantes.
4. **Cota Parlamentar / CEAP (Câmara)**: Auditoria de reembolsos de gastos de exercício de mandato parlamentar (alimentação, passagens, combustíveis, consultorias).

---

## 2. Esquema TSE: Candidatos e Despesas de Campanha

### 2.1 Origem dos Dados
- **Fontes**:
  - `consulta_cand_{ANO}_{UF}.csv` (Cadastro de Candidatos)
  - `despesas_pagas_candidatos_{ANO}_{UF}.csv` (Prestação de Contas - Despesas Pagas)
- **Ano Prioritário**: `2022` (Eleição Geral Federal/Estadual)
- **Encoding original dos CSVs**: `latin1` (`ISO-8859-1`)
- **Separador**: Ponto e vírgula (`;`)

### 2.2 Atributos Selecionados e Tipagem

| Coluna | Tipo Primitivo | Tipo Polars / DuckDB | Nullable | Descrição / Regra de Negócio |
|---|---|---|---|---|
| `ANO_ELEICAO` | `int` | `Int32` | Não | Ano do pleito eleitoral (ex.: `2022`). Chave de particionamento físico. |
| `SG_UF` | `str` | `String` | Não | Sigla da Unidade Federativa da candidatura (ex.: `'SP'`, `'RJ'`, `'DF'`, `'BR'`). |
| `SQ_CANDIDATO` | `int` | `Int64` | Não | Sequencial único do candidato gerado pelo TSE (chave de junção entre candidatos, despesas e bens). |
| `NM_CANDIDATO` | `str` | `String` | Não | Nome civil completo do candidato (utilizado para matching canônico). |
| `NM_URNA_CANDIDATO` | `str` | `String` | Não | Nome registrado para exibição na urna eletrônica (utilizado para matching fuzzy via RapidFuzz). |
| `SG_PARTIDO` | `str` | `String` | Não | Sigla partidária do candidato no pleito (ex.: `'PT'`, `'PL'`, `'MDB'`). |
| `DS_CARGO` | `str` | `String` | Não | Descrição formal do cargo concorrido (ex.: `'Presidente'`, `'Governador'`, `'Deputado Federal'`). |
| `VR_PAGTO_DESPESA` | `float` | `Float64` | Não | Valor monetário pago da despesa (R$). Requer transformação no ETL: substituição de vírgula decimal `,` por ponto `.`. |

### 2.3 Atributos Adicionais Opcionais de Suporte (Detalhamento de Contexto)
- `DS_TIPO_DESPESA` (`String`): Descrição sumária da despesa (ex.: *Publicidade por materiais impressos*).
- `NM_FORNECEDOR` (`String`): Razão social ou nome fantasia do fornecedor pago.

### 2.4 Colunas Eliminadas (Poda de Redundâncias)
- Códigos duplicados de tabelas dimensionais: `CD_TIPO_ELEICAO`, `CD_SITUACAO_CANDIDATURA`, `CD_DETALHE_SITUACAO_CAND`.
- Informações burocráticas irrelevantes para o fact-checking: `DT_GERACAO`, `HH_GERACAO`, `NR_PROCESSO`, `CD_MUNICIPIO_NASCIMENTO`.

---

## 3. Esquema TSE: Declaração de Bens dos Candidatos

### 3.1 Origem dos Dados
- **Fonte**: `bem_candidato_{ANO}_{UF}.csv` (Inventário Patrimonial)
- **Ano Prioritário**: `2022`
- **Encoding original dos CSVs**: `latin1` (`ISO-8859-1`)
- **Separador**: Ponto e vírgula (`;`)

### 3.2 Atributos Selecionados e Tipagem

| Coluna | Tipo Primitivo | Tipo Polars / DuckDB | Nullable | Descrição / Regra de Negócio |
|---|---|---|---|---|
| `ANO_ELEICAO` | `int` | `Int32` | Não | Ano do pleito eleitoral (ex.: `2022`). Chave de particionamento físico. |
| `SG_UF` | `str` | `String` | Não | Sigla da Unidade Federativa da candidatura. |
| `SQ_CANDIDATO` | `int` | `Int64` | Não | Sequencial do candidato (chave de junção com a tabela de candidatos e despesas). |
| `DS_TIPO_BEM_CANDIDATO` | `str` | `String` | Não | Classificação oficial do bem (ex.: *Imóvel residencial*, *Veículo automotor*, *Dinheiro em espécie*, *Quotas de empresa*). |
| `DS_BEM_CANDIDATO` | `str` | `String` | Sim | Descrição textual detalhada do patrimônio declarada pelo candidato. |
| `VR_BEM_CANDIDATO` | `float` | `Float64` | Não | Valor monetário atribuído ao bem (R$). Requer conversão de vírgula para ponto e cast para Float64. |

### 3.3 Colunas Eliminadas (Poda de Redundâncias)
- Códigos internos de tipagem redundantes: `CD_TIPO_BEM_CANDIDATO`, `NR_ORDEM_CANDIDATO`, `DT_GERACAO`, `HH_GERACAO`.

---

## 4. Esquema Câmara dos Deputados: Votações Nominais e Proposições

### 4.1 Origem dos Dados
- **Fontes**: 
  - `votacoesVotos-{ANO}.csv` (Votos individuais por sessão e deputado)
  - `votacoes-{ANO}.csv` (Metadados da sessão e vinculação à proposição)
- **Anos Prioritários**: `2023` e `2024` (57ª Legislatura)
- **Encoding original dos CSVs**: `utf-8`
- **Separador**: Ponto e vírgula (`;`)

### 4.2 Atributos Selecionados e Tipagem

| Coluna Padronizada | Coluna Bruta Original | Tipo Primitivo | Tipo Polars / DuckDB | Nullable | Descrição / Regra de Negócio |
|---|---|---|---|---|---|
| `idVotacao` | `idVotacao` | `str` | `String` | Não | Identificador único alfanumérico da sessão de votação na Câmara. |
| `uriVotacao` | `uriVotacao` | `str` | `String` | Sim | URL / URI oficial com os dados abertos da votação. |
| `data` | `dataHoraVoto` | `date` | `Date32` / `String` | Não | Data oficial da votação (extraída em formato ISO `YYYY-MM-DD`). |
| `idDeputado` | `deputado_id` | `int` | `Int64` | Não | Identificador numérico do parlamentar na base da Câmara. |
| `nomeDeputado` | `deputado_nome` | `str` | `String` | Não | Nome parlamentar registrado (alvo de desambiguação e fuzzy matching). |
| `siglaPartido` | `deputado_siglaPartido` | `str` | `String` | Não | Sigla do partido político no instante da votação. |
| `siglaUf` | `deputado_siglaUf` | `str` | `String` | Não | UF de representação do parlamentar (ex.: `'SP'`, `'MG'`). |
| `voto` | `voto` | `str` | `String` | Não | Voto emitido (ex.: `'Sim'`, `'Não'`, `'Abstenção'`, `'Obstrução'`, `'Artigo 17'`). |
| `proposicao_id` | `ultimaApresentacaoProposicao_idProposicao` | `str` | `String` | Sim | Identificador da proposição associada (PL, PEC, MPV) para vinculação do tema. |

### 4.3 Atributos Adicionais Opcionais de Suporte
- `proposicao_descricao` (`String`): Descrição do objeto da votação (obtida de `votacoes.csv` campo `descricao`).
- `proposicao_ementa` (`String`): Ementa legislativa da matéria (utilizada para indexação vetorial/RAG).

### 4.4 Colunas Eliminadas (Poda de Redundâncias)
- Links de fotos e URIs redundantes: `deputado_urlFoto`, `deputado_uri`, `deputado_uriPartido`.
- Timestamps de auditoria em milissegundos e chaves de sessão secundárias.

---

## 5. Esquema Câmara dos Deputados: Cota Parlamentar (CEAP)

### 5.1 Origem dos Dados
- **Fontes**: `Ano-{ANO}.csv` (Dados Abertos da Câmara dos Deputados)
- **Anos Prioritários**: `2023` e `2024`
- **Encoding original dos CSVs**: `utf-8` / `latin1`
- **Separador**: Ponto e vírgula (`;`)

### 5.2 Atributos Selecionados e Tipagem

| Coluna | Tipo Primitivo | Tipo Polars / DuckDB | Nullable | Descrição / Regra de Negócio |
|---|---|---|---|---|
| `idDeputado` | `int` | `Int64` | Não | Identificador único do parlamentar (chave de ligação com votações). |
| `txNomeParlamentar` | `str` | `String` | Não | Nome parlamentar do deputado. |
| `sgPartido` | `str` | `String` | Não | Sigla do partido político no momento da despesa. |
| `sgUF` | `str` | `String` | Não | UF de representação do deputado. |
| `numAno` | `int` | `Int32` | Não | Ano da emissão do comprovante/despesa. |
| `numMes` | `int` | `Int32` | Não | Mês da despesa (1 a 12). |
| `txtDescricao` | `str` | `String` | Não | Categoria da despesa (ex.: *PASSAGEM AÉREA*, *COMBUSTÍVEIS E LUBRIFICANTES*, *FORNECIMENTO DE ALIMENTAÇÃO DO PARLAMENTAR*). |
| `txtFornecedor` | `str` | `String` | Não | Nome ou razão social do prestador do serviço/fornecedor. |
| `txtCNPJCPF` | `str` | `String` | Sim | Cadastro de pessoa jurídica ou física do fornecedor. |
| `vlrLiquido` | `float` | `Float64` | Não | Valor líquido final pago/reembolsado pela Câmara (R$). |

### 5.3 Colunas Eliminadas (Poda de Redundâncias)
- Códigos de lote e subcotas internas: `ideCadastro`, `nuCarteiraParlamentar`, `codLegislatura`, `numSubCota`, `numEspecificacaoSubCota`, `ideDocumento`.
- Links de notas fiscais digitalizadas e chaves de protocolo financeiro.

---

## 6. Diretrizes de Ingestão e Armazenamento (ETL -> Parquet)

1. **Particionamento Físico e Organização**:
   - TSE Despesas: `data/processed/tse/despesas/ano={ANO}/*.parquet`
   - TSE Bens: `data/processed/tse/bens/ano={ANO}/*.parquet`
   - Câmara Votações: `data/processed/camara/votacoes/ano={ANO}/*.parquet`
   - Câmara CEAP: `data/processed/camara/ceap/ano={ANO}/*.parquet`
2. **Compressão**:
   - `zstd` (Zstandard) configurada nativamente com nível 3 de compressão para garantir redução $\ge 70\%$ sobre CSVs brutos.
3. **Regras de Conversão Obrigatórias**:
   - Valores monetários (`VR_PAGTO_DESPESA`, `VR_BEM_CANDIDATO`, `vlrLiquido`): limpeza de caracteres extras, substituição de vírgula `,` por ponto `.` e cast estrito para `Float64`.
   - Datas: padronização no formato ISO `YYYY-MM-DD` (`Date32`).
4. **Modo de Consulta Analítica**:
   - **DuckDB** configurado exclusivamente em modo `read_only=True` sobre os arquivos Parquet via globbing (`read_parquet('data/processed/**/*.parquet')`).

---

## 7. Matriz de Rastreabilidade e Validação

| Papel | Responsável | Status | Data |
|---|---|---|---|
| **Product Owner (P.O.)** | Eduarda | `[ ] Pendente de Aprovação` | 22/09/2026 |
| **Scrum Master** | Yan | `[X] Revisado` | 22/09/2026 |
| **Engenharia de Dados** | Davi / Ester / Ruan | `[X] Implementado` | 22/09/2026 |
