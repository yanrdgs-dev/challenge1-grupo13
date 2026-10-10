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
- **Anos Prioritários**: `2026` (Ano Corrente) / `2022` (Eleição Geral Anterior)
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
- **Anos Prioritários**: `2026` / `2022`
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
- **Anos Prioritários**: `2026` (Ano Corrente) / `2024` e `2025`
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
- **Anos Prioritários**: `2026` (Ano Corrente) / `2024` e `2025`
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

---

## Regra de detecção automática de schema (poda)

A poda automática (`prune_redundant`) só se aplica quando a tabela é reconhecida sem ambiguidade:

- `tse_candidatos`: tem `SQ_CANDIDATO` e `NM_URNA_CANDIDATO` ou `CD_CARGO` **e nenhuma medida de fato** (colunas `QT_*` ou `VR_RECEITA`, `VR_DESPESA_CONTRATADA`, `VR_PAGTO_DESPESA`; `NR_TURNO` e `VR_DESPESA_MAX_CAMPANHA` existem no cadastro e não contam). Tabelas de resultado (votação por zona e por seção), receitas e despesas contratadas também têm `SQ_CANDIDATO`, mas carregam votos e valores que o schema de cadastro descartaria.
- `tse_despesas`: tem `VR_PAGTO_DESPESA` **e** `SQ_CANDIDATO`. As despesas pagas de 2022 vêm por prestador de contas (`SQ_PRESTADOR_CONTAS`), sem coluna de candidato, e por isso não são podadas.
- Tabela não reconhecida mantém todas as colunas.

## Normalizações específicas por fonte

- **CEAP da Câmara** (`camara_ceap`): preserva `ideCadastro`, a chave de junção com o cadastro de deputados usada por `build_dim_politicos`.
- **Cadastro de senadores**: a fonte automática (`senador/lista/atual.csv`) é um XML achatado, com cabeçalhos em forma de caminho e uma linha por suplente/exercício. `src/etl/senado_cadastro.py` a reduz a uma linha por senador com `Codigo Parlamentar`, `Nome Parlamentar`, `Nome Completo`, `Partido`, `UF`, `Email`, `Titular/Suplente` e `Mandato` (ex.: `2023-2031`). Entrada já no formato legível passa sem alteração.

---

## 8. Esquema real dos parquets do TSE (descoberta da Fase 1)

Medido em 2026-10-10 sobre os parquets gerados pela ingestão (`data/processed/tse/`), 2022 e 2026. Os números de 2026 mudam a cada carga: o TSE ainda publica dados dessa eleição. Para reproduzir:

```python
import duckdb
rel = "read_parquet('data/processed/tse/votacao_munzona/**/*.parquet', hive_partitioning=true, union_by_name=true)"
duckdb.sql(f"select NR_TURNO, NM_URNA_CANDIDATO, sum(QT_VOTOS_NOMINAIS_VALIDOS) from {rel} where DS_CARGO='Presidente' group by 1,2 order by 1,3 desc").show()
```

### 8.1 Inventário

| Parquet | Uma linha é | Linhas | Anos | Chave |
|---|---|---:|---|---|
| `candidatos` | candidatura **por turno** | 50.331 | 2022, 2026 | `SQ_CANDIDATO` (+ turno, ver 8.5) |
| `candidatos_complementar` | idem (detalhes da candidatura) | 50.331 | 2022, 2026 | `SQ_CANDIDATO` |
| `bens` | bem declarado | 170.002 (32.166 candidatos) | 2022, 2026 | `SQ_CANDIDATO` |
| `cassacao` | motivo de cassação/indeferimento | 3.747 | 2022, 2026 | `SQ_CANDIDATO` |
| `coligacoes` | coligação ou federação | 9.002 | 2022, 2026 | `SQ_COLIGACAO` |
| `redes_sociais` | link de rede social | 171.650 (34.251 candidatos) | 2022, 2026 | `SQ_CANDIDATO` |
| `votacao_munzona` | candidato × município × zona × turno × cargo | 9.377.845 | **só 2022** | `SQ_CANDIDATO` |
| `detalhe_votacao_secao` | seção × turno × cargo | 3.078.727 | **só 2022** | `NR_ZONA`, `NR_SECAO` |
| `totalizacao_presidente_2022` | instante de totalização (histórico) | 13.723 | só 2022 | — |
| `prestacao_contas/receitas` | receita | 849.638 | 2022, 2026 | `SQ_CANDIDATO`, `SQ_PRESTADOR_CONTAS` |
| `prestacao_contas/despesas_contratadas` | despesa contratada | 3.205.773 | 2022, 2026 | `SQ_CANDIDATO`, `SQ_PRESTADOR_CONTAS` |
| `prestacao_contas/despesas_pagas` | despesa paga | 3.127.248 | 2022, 2026 | `SQ_PRESTADOR_CONTAS` apenas |

Os parquets são particionados por `ano=`. Em 2026 o TSE já publica candidatos, bens, prestação de contas e redes sociais, mas **não** votação nem totalização (`resultados-2026` só tem relatórios em PDF).

### 8.2 Domínios de valores

- **Turno (`NR_TURNO`, `ST_TURNO`):** 1 e 2. Em 2022 o 2º turno existiu só para Presidente (2 candidatos) e Governador (12 UFs, 24 candidatos). Em 2026 já há candidaturas de 2º turno em `candidatos` (Presidente: LULA e FLAVIO BOLSONARO; Governador: 8 linhas), mas esse turno ainda não aconteceu e não há resultado algum.
- **Cargo (`DS_CARGO`):** a caixa muda entre tabelas, então toda tool deve normalizar.
  - `candidatos`, `candidatos_complementar`: `PRESIDENTE`, `VICE-PRESIDENTE`, `GOVERNADOR`, `VICE-GOVERNADOR`, `SENADOR`, `1º SUPLENTE`, `2º SUPLENTE`, `DEPUTADO FEDERAL`, `DEPUTADO ESTADUAL`, `DEPUTADO DISTRITAL`.
  - `votacao_munzona`, `detalhe_votacao_secao`, `prestacao_contas`: `Presidente`, `Governador`, `Senador`, `Deputado Federal`, `Deputado Estadual`, `Deputado Distrital` (o detalhe por seção acrescenta `Conselheiro Distrital`; a prestação acrescenta `Vice-governador`).
- **UF (`SG_UF`):** as 27 UFs. Em `candidatos`, `BR` identifica Presidente e Vice. Na votação, o voto no exterior vem como `ZZ` (294.525 votos para Presidente no 1º turno de 2022) e não existe `BR`: o total nacional soma as 27 UFs **mais `ZZ`**.
- **Situação da candidatura (`DS_SITUACAO_CANDIDATURA`):** 2022 tem `APTO` (26.409) e `INAPTO` (2.913); em **2026 todas as linhas são `#NE`**. O detalhe (`DS_DETALHE_SITUACAO_CAND` na votação): `DEFERIDO`, `INDEFERIDO`, `INDEFERIDO COM RECURSO`, `DEFERIDO COM RECURSO`, `RENÚNCIA`, `PEDIDO NÃO CONHECIDO`, `PENDENTE DE JULGAMENTO`.
- **Resultado (`DS_SIT_TOT_TURNO`, na votação):** `ELEITO`, `ELEITO POR QP`, `ELEITO POR MÉDIA`, `2º TURNO`, `SUPLENTE`, `NÃO ELEITO`.
- **Destino do voto (`NM_TIPO_DESTINACAO_VOTOS`):** `Válido`, `Válido (legenda)`, `Anulado`, `Anulado sub judice`.

### 8.3 Semântica dos campos críticos

- **`QT_VOTOS_NOMINAIS` inclui votos anulados; `QT_VOTOS_NOMINAIS_VALIDOS` não.** O resultado oficial é o segundo. A diferença em 2022: Deputado Federal 1.021.815, Deputado Estadual 1.580.492, Senador 534.610, Governador (1º turno) 194.850; para Presidente é zero. Somar `QT_VOTOS_NOMINAIS` superestima quem teve candidatura indeferida (PABLO MARÇAL: 243.037 votos anulados, 0 válidos).
- **Conferência com o resultado oficial de 2022** (soma de `QT_VOTOS_NOMINAIS_VALIDOS`): Presidente 1º turno LULA 57.259.504 e JAIR BOLSONARO 51.072.345; 2º turno 60.345.999 e 58.206.354. Eleitos: 513 Deputados Federais, 27 Senadores, 1 Presidente (no 2º turno), 15 Governadores no 1º turno e 12 no 2º, 1.035 Deputados Estaduais e 24 Distritais.
- **Comparecimento (`detalhe_votacao_secao`), Presidente, 1º turno de 2022:** aptos 156.454.011; comparecimento 123.682.372; abstenções 32.770.982; brancos 1.964.779; nulos 3.487.874; válidos 118.229.719.
- **`totalizacao_presidente_2022` não deve ser usada para resultado:** é um histórico largo (uma coluna por candidato), todo em texto, com espaços no fim dos nomes de coluna (`DT_TOTALIZACAO     `). O resultado vem de `votacao_munzona`.
- **Prestação de contas:** valores em reais (`Float64`). `despesas_pagas` **não tem candidato nem cargo**, só `SQ_PRESTADOR_CONTAS`; o candidato se obtém por `receitas` ou `despesas_contratadas`, onde `SQ_PRESTADOR_CONTAS` ↔ `SQ_CANDIDATO` é 1:1 (nenhum prestador com dois candidatos) e cobre 100% dos 36.431 prestadores de `despesas_pagas`.
- **Bens:** 676 linhas com valor zero e 5 negativas; 11.021 candidaturas de 2022 não têm nenhum bem declarado. Ausência de linha não é patrimônio zero declarado.

### 8.4 Valores sentinela

O TSE preenche campos sem valor com marcadores. Toda tool deve tratá-los como "sem dado" (`None`), nunca como valor.

| Marcador | Onde aparece (exemplos) |
|---|---|
| `#NULO` | `NM_SOCIAL_CANDIDATO` (9,4 mi de linhas), `NM_FEDERACAO`, `SG_FEDERACAO` |
| `#NE` | `DS_SITUACAO_JULGAMENTO`, `DS_SITUACAO_CASSACAO`, `DS_SITUACAO_CANDIDATURA` (todo o 2026) |
| `#NULO#` | `DS_MODELO_URNA`, `NM_LOCAL_VOTACAO` |
| `-1`, `-3`, `-4` | colunas `CD_*` e `NR_*` (`CD_SITUACAO_JULGAMENTO`, `NR_FEDERACAO`, `NR_PROTOCOLO_CANDIDATURA`...) |

Cuidado: existem dados reais que começam com `#` (`#TO COM LORA` em `NM_URNA_CANDIDATO`; URLs como `#MARINA_MARI_LOPES`), então a comparação precisa ser com os marcadores exatos, não com "começa com #".

### 8.5 Chaves, junções e homônimos (regra 2)

- `SQ_CANDIDATO` é único por candidatura e **não colide entre anos** (nenhum aparece em 2022 e 2026). Mas ele **se repete por turno**: há 72 `SQ_CANDIDATO` com duas linhas em `candidatos` (os candidatos de 2º turno de 2022 e de 2026). Sem a coluna `NR_TURNO` essas linhas são indistinguíveis (problema 1 em 8.6).
- Toda `SQ_CANDIDATO` da votação de 2022 existe em `candidatos` (26.237 de 26.237), e todo candidato das receitas existe no cadastro (47.181 de 47.181).
- **Homônimos:** 173 grupos com o mesmo nome de urna, UF, cargo e ano e `SQ_CANDIDATO` diferentes (96 em Deputado Federal, 65 em Deputado Estadual); em 161 deles o partido também é o mesmo, então partido não desempata. O que desempata é `NR_CANDIDATO` (número na urna) ou o nome civil. A resolução de candidato deve devolver "ambíguo" (regra 2) e a tool, INCONCLUSIVO, em vez de escolher.

### 8.6 Problemas encontrados no ETL

1. **`candidatos` perdeu `NR_TURNO`** na poda: as 72 linhas de 2º turno ficaram duplicadas e sem como saber de qual turno é cada uma. Também perdeu `DS_SIT_TOT_TURNO`.
2. **Sem dados de perfil:** `DS_GENERO`, `DS_GRAU_INSTRUCAO`, `DS_ESTADO_CIVIL`, `DS_COR_RACA`, `DS_OCUPACAO` e `SG_UF_NASCIMENTO` foram podados, e o `candidatos_complementar` não os tem (traz idade na posse, reeleição, situação detalhada, nacionalidade). Sem eles não há `check_candidate_profile`. CPF, título de eleitor, e-mail e data de nascimento continuam fora, de propósito.
3. **Votação, detalhe por seção e totalização só existem para 2022**, e o TSE 2026 ainda não publicou resultados.
4. **Caixa de `DS_CARGO` diferente** entre as tabelas (8.2).

### 8.7 Mapeamento proposto das tools para os parquets

| Tool (passos 2 a 4 da Fase 1) | Parquet | Observação |
|---|---|---|
| `resolve_candidate` (nova, regra 2) | `candidatos` | nome + UF + cargo + ano (+ número); devolve `SQ_CANDIDATO`, ou ambíguo |
| `get_election_result`, `get_candidate_votes` | `votacao_munzona` | somar `QT_VOTOS_NOMINAIS_VALIDOS`; nacional inclui `ZZ`; exigir ano e turno |
| `check_candidate_status` | `candidatos`, `candidatos_complementar`, `votacao_munzona` | situação, detalhe e `DS_SIT_TOT_TURNO` |
| `check_disqualification_motive` | `cassacao`, `candidatos_complementar` | |
| `check_candidate_profile` | `candidatos` (após corrigir 8.6) | |
| `get_candidate_assets`, `check_cash_and_special_assets` | `bens` | zero/negativo e ausência não são patrimônio |
| `verify_official_social_media` | `redes_sociais` | só os links que o candidato registrou no TSE |
| Finanças de campanha | `receitas`, `despesas_contratadas`, `despesas_pagas` | `despesas_pagas` por `SQ_PRESTADOR_CONTAS` |
| Participação (comparecimento, abstenção, brancos e nulos) | `detalhe_votacao_secao` | não estava no plano; as claims de participação precisam dele |

Guardas de especificidade (regra 3): ano ausente, turno ambíguo ("o primeiro turno", "a última eleição") e qualquer resultado de 2026 devem dar INCONCLUSIVO sem chamar tool de dado.
