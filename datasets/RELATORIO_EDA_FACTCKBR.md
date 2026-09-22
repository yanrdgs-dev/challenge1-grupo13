# Análise Exploratória de Dados (EDA): FACTCKBR
**Dataset de Checagem de Fatos da Política Brasileira (Fact-Checking)**

---

## 1. Visão Geral e Características do Dataset

O dataset **FACTCKBR** (`FACTCKBR.tsv`) é uma base de dados estruturada contendo alegações checadas e seus respectivos vereditos, coletadas a partir das três principais agências de checagem de fatos do Brasil signatárias da *International Fact-Checking Network* (IFCN): **Agência Lupa**, **Agência Pública** (projeto *Truco*) e **Aos Fatos**.

### 1.1 Metadados Estruturais
- **Formato do Arquivo:** TSV (*Tab-Separated Values*), codificação UTF-8.
- **Dimensões:** **1.313 linhas** (registros de declarações checadas) e **9 colunas**.
- **Período Temporal:** De **26 de fevereiro de 2016** a **22 de julho de 2019** (cobrindo eventos históricos cruciais como o impeachment de Dilma Rousseff, as eleições presidenciais de 2018 e o primeiro semestre do governo Bolsonaro).

### 1.2 Dicionário de Variáveis
| Coluna | Tipo Inferido | Descrição | Nulos (%) |
| :--- | :--- | :--- | :--- |
| `URL` | String (URI) | Link permanente da reportagem de checagem | 0 (0,0%) |
| `Author` | String (URI) | Identificação da agência checadora | 0 (0,0%) |
| `datePublished` | String (Data/Hora) | Data e/ou timestamp da publicação | 0 (0,0%) |
| `claimReviewed` | String (Texto) | A frase, alegação ou citação que foi verificada | 13 (0,99%) |
| `reviewBody` | String (Texto) | Síntese do contexto, apuração e justificativa | 12 (0,91%)* |
| `title` | String (Texto) | Título da matéria de checagem publicada | 0 (0,0%) |
| `ratingValue` | Float64 / Numérico | Nota numérica da checagem (conforme Schema.org) | 4 (0,30%) |
| `bestRating` | Int64 / Numérico | Pontuação máxima da escala da agência checadora | 0 (0,0%) |
| `alternativeName` | String (Texto) | Veredito categórico em linguagem natural | 4 (0,30%) |

*\*Nota: Conforme detalhado na seção de qualidade, 528 linhas possuem o texto `"Empty"` no lugar de valores nulos reais.*

---

## 2. Principais Padrões Identificados

### 2.1 Desbalanceamento Severo de Classes (Vereditos)
A análise dos vereditos categóricos revela um forte desbalanceamento: a grande maioria das declarações analisadas pelas agências recebe o selo de **Falso**.
- **Falso:** **943 casos (71,8%)**
- **Verdadeiro:** **120 casos (9,1%)**
- **Exagerado:** **91 casos (6,9%)**
- **Distorcido:** **54 casos (4,1%)**
- **Sem contexto:** **42 casos (3,2%)**
- **Impossível provar:** **20 casos (1,5%)**
- **Discutível:** **12 casos (0,9%)**
- **Outros/Raros:** **31 casos (2,4%)**

> **Interpretação:** As agências atuam com base em pautas e denúncias sociais; logo, boatos virais e informações fraudulentas com alto potencial de dano recebem muito mais atenção do que declarações verdadeiras de rotina.

### 2.2 Relação N-para-1 entre Declarações e Artigos (Multi-Claims)
- Existem **984 URLs únicas** para 1.313 registros.
- **329 registros** compartilham a mesma URL com outras linhas.
- Uma única reportagem (ex: checagem de debates presidenciais na TV ou sabatinas) costuma conter a checagem de **até 11 declarações distintas** na mesma página.

### 2.3 Sazonalidade e Pico Eleitoral (Série Temporal)
- A produção de checagens é fortemente condicionada pelo calendário político nacional:
  - **2016 (78 checagens):** Foco no impeachment de Dilma Rousseff e início do governo Temer (quase exclusivamente coberto pela Agência Pública no dataset).
  - **2017 (124 checagens):** Discussões sobre reformas trabalhista e previdenciária.
  - **2018 (604 checagens):** Explosão no volume de publicações, culminando no **pico histórico em Outubro de 2018 (154 checagens em um único mês)** decorrente das Eleições Presidenciais de 2018.
  - **2019 (507 checagens até julho):** Alto volume mantido pelo início do mandato de Jair Bolsonaro e discussões da Reforma da Previdência.

### 2.4 Foco Temático e Figuras Políticas Centrais
A análise léxica das declarações revelou as entidades e temas mais verificados:
1. **Jair Bolsonaro:** 329 menções (**25,1%** de todas as alegações)
2. **Luiz Inácio Lula da Silva:** 130 menções (**9,9%**)
3. **Partido dos Trabalhadores (PT):** 90 menções (**6,9%**)
4. **Fernando Haddad:** 87 menções (**6,6%**)
5. **Michel Temer:** 47 menções (**3,6%**)
6. **Dilma Rousseff:** 44 menções (**3,4%**)
7. **Sergio Moro:** 42 menções (**3,2%**)
8. **Reforma da Previdência:** 35 menções (**2,7%**)

---

## 3. Avaliação da Qualidade dos Dados (Data Quality Assessment)

Durante a análise exploratória, foram descobertas falhas estruturais críticas decorrentes do processo de scraping e padronização original dos dados:

### 3.1 Anomalia Crítica no campo `ratingValue` (Agência Lupa)
- Em todos os **528 registros da Agência Lupa**, o campo `ratingValue` está preenchido estaticamente com o valor **`4.0`**, independentemente do veredito real:
  - 469 alegações *Falsas* têm `ratingValue = 4.0`
  - 34 alegações *Verdadeiras* têm `ratingValue = 4.0`
  - 12 alegações *Exageradas* têm `ratingValue = 4.0`
- **Impacto:** O campo numérico `ratingValue` **não pode ser utilizado como variável alvo** para treinamento de modelos de regressão ou ordenação ordinal sem prévia reconstrução.

### 3.2 Ocultação de Valores Nulos ("Empty" na Lupa)
- Todos os **528 registros da Agência Lupa** têm a coluna `reviewBody` preenchida com o texto literal `"Empty"`.
- O scraper não extraiu o texto explicativo da Lupa, reduzindo a completude de texto explicativo a apenas **59,4%** do dataset total (presente apenas em Aos Fatos e Agência Pública).

### 3.3 Disparidade de Escalas e Taxonomias entre Agências
- **Agência Pública:** Escala de 1 a 8 (`bestRating=8`). Mapeia ordinalmente do falso (1) ao verdadeiro (8).
- **Aos Fatos:** Escala de 0 a 6 (`bestRating=5`). 1 = Falso, 3 = Distorcido, etc.
- **Agência Lupa:** `bestRating=6`, mas com `ratingValue` fixo em 4.0.

### 3.4 Inconsistência de Caixa Alta/Baixa
- A coluna `alternativeName` possui variações de caixa: `"Falso"` (615) vs `"falso"` (328), `"Distorcido"` (25) vs `"distorcido"` (29), `"Exagerado"` (87) vs `"exagerado"` (4). A normalização de strings é indispensável.

### 3.5 Outliers e Erros de Extração Textual (`claimReviewed`)
- Em pelo menos **4 registros da Agência Pública** (ex: linhas 712, 714, 765 e 781), o scraper capturou o **artigo jornalístico inteiro** (até 9.606 caracteres e mais de 1.500 palavras) dentro do campo `claimReviewed`, em vez de isolar apenas a declaração checada.

---

## 4. Desafios e Oportunidades para Próximas Etapas

### 4.1 Principais Desafios
1. **Risco de Viés por Desbalanceamento:** Modelos de classificação supervisionada tendem a colapsar para a classe majoritária (72% Falso). Será necessário aplicar técnicas como reponderação de perdas (*class weights*), *focal loss*, ou estratégias de *resampling* / SMOTE textual.
2. **Inconsistência da Variável Alvo:** Recomenda-se colapsar as taxonomias em:
   - **Binária:** `Falso / Enganoso` vs `Verdadeiro`
   - **Ternária:** `Falso`, `Parcial / Nuance` (Exagerado, Distorcido, Sem contexto), `Verdadeiro`
3. **Limpeza e Filtragem de Ruído:** Tratamento obrigatório para remoção dos outliers de tamanho textual e imputação correta de nulos.

### 4.2 Oportunidades Técnicas e de Modelagem
1. **Classificação Automática de Notícias Falsas (NLP):**
   - Utilização de embeddings pré-treinados em português (como `BERTimbau` / `neuralmind/bert-base-portuguese-cased`) alimentados com o par (`claimReviewed`, `title`).
2. **Enriquecimento dos Dados via Web Scraping:**
   - Como o campo `URL` possui 100% de integridade, é possível desenvolver um crawler complementar para extrair o texto faltante da Lupa (`reviewBody`) e reparar os outliers da Pública.
3. **Claim Matching & Deduplicação de Checagens:**
   - Identificar alegações concorrentes checadas simultaneamente por mais de uma agência utilizando busca semântica por similaridade de cosseno (Dense Retrieval / Sentence-BERT).
4. **Análise de Redes e Disseminação Temática:**
   - Mapear a dinâmica temporal da desinformação em torno de temas institucionais (urnas, vacinas, previdência) e atores eleitorais.

---

## 5. Gráficos de Suporte (Gerados na Pasta `eda_charts/`)

Os gráficos a seguir foram gerados e estão disponíveis em alta resolução para visualização e apresentação:
1. `eda_charts/01_volume_por_agencia.png`: Volume total de declarações vs. URLs únicas por agência.
2. `eda_charts/02_distribuicao_vereditos.png`: Distribuição percentual dos vereditos (desbalanceamento).
3. `eda_charts/03_vereditos_por_agencia.png`: Perfil de distribuição de vereditos por agência checadora.
4. `eda_charts/04_anomalia_rating_value.png`: Demonstração gráfica da anomalia de `ratingValue` fixo em 4.0 na Lupa.
5. `eda_charts/05_serie_temporal_eleicoes.png`: Evolução mensal das checagens e pico eleitoral de 2018.
6. `eda_charts/06_qualidade_textos_e_outliers.png`: Boxplots de extensão textual e integridade do `reviewBody`.
7. `eda_charts/07_atores_e_temas_politicos.png`: Menções aos principais personagens e assuntos políticos.
