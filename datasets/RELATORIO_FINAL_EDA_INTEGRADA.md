# Relatório Final Consolidado de Análise Exploratória de Dados (EDA)
## Ecossistema de Dados para o Chatbot Agêntico de Fact-Checking Político e Eleitoral
**Consolidação Integral: FACTCKBR, TSE, Câmara dos Deputados e Senado Federal (2016–2026)**

---

## 1. Visão Geral, Arquitetura e Propósito dos Dados

O objetivo central deste projeto é a construção de um **Chatbot Agêntico especializado em Fact-Checking político e eleitoral**. Diferente de chatbots genéricos baseados exclusivamente na memória paramétrica de Grandes Modelos de Linguagem (LLMs) — altamente propensos a alucinações factuais e anacronismos temporais —, o nosso agente é orientado a **ferramentas de checagem determinísticas (*Tool-Use / Function Calling*)** conectadas a uma base de conhecimento de dados públicos auditáveis.

Para cumprir esse propósito, o projeto integrou duas grandes frentes de dados:
1.  **O Benchmark de Treinamento e Padrões de Desinformação (`FACTCKBR.tsv`):** Acervo histórico (2016–2019) das três principais agências de checagem brasileiras (*Agência Lupa*, *Aos Fatos* e *Agência Pública*). Serve para entender a tipologia das alegações virais, os temas mais propensos a boatos e a linguagem de declarações políticas falsas.
2.  **O Repositório Analítico Estruturado para as Ferramentas do Agente (`data/processed/`):** 19 conjuntos de dados públicos consolidados do **Tribunal Superior Eleitoral (TSE)**, da **Câmara dos Deputados** e do **Senado Federal** cobrindo o período de **2022 a 2026**, convertidos de ~16 GB de CSVs brutos para **~855 MB em Apache Parquet** com particionamento temporal e compressão Zstandard.

```
                                      ARQUITETURA GERAL DO SISTEMA DE FACT-CHECKING
                                     
   [ Alegação / Pergunta do Usuário ] ──► [ LLM Orquestrador (src/core/llm_client.py) ]
                                                              │
                                      ┌───────────────────────┴────────────────────────┐
                                      ▼                                                ▼
                         [ Benchmark / Few-Shot NLP ]                     [ Tools Especializadas (src/tools/) ]
                         - Dataset FACTCKBR (1.313 claims)                 - Perfil & Elegibilidade (TSE)
                         - Classificação de Veredito                      - Auditoria Patrimonial (Bens/Espécie)
                         - Padrões de Falácias Políticas                  - Redes Oficiais Homologadas
                                                                          - Gastos de Mandato & NF-e (CEAP/CEAPS)
                                                                          - Cruzamento Fornecedores Mandato ↔ TSE
                                                                          - Autoria Real vs Apoio (Câmara/Senado)
                                                                          - Rastreabilidade de Leis & Textos PDF
```

A seguir, apresenta-se a consolidação analítica de todos os eixos investigados, formulando uma **hipótese causal e investigativa** para cada achado empírico e visualização gerada.

---

## 2. Eixo 0: Análise do Benchmark de Fact-Checking (FACTCKBR)

O dataset `FACTCKBR.tsv` compreende **1.313 registros de alegações checadas** publicadas entre 26 de fevereiro de 2016 e 22 de julho de 2019, estruturadas sob o padrão Schema.org *ClaimReview*.

### 2.1 Desbalanceamento Severo de Vereditos (Gráfico 02 - FACTCKBR)
*   **Dado Empírico:** **71,8% das declarações (943 casos)** receberam o selo de **Falso**. Vereditos como *Verdadeiro* somam apenas 9,1% (120 casos), enquanto categorias de nuance (*Exagerado*, *Distorcido*, *Sem Contexto*) somam 14,2%.
*   **Hipótese Explicativa:** Agências de checagem operam sob uma lógica de seleção reativa orientada ao dano social potencial (*harm reduction*). Declarações verdadeiras ou consensuais de agentes públicos não geram demanda de apuração jornalística; logo, a curadoria humana das agências prioriza desmentir falsidades altamente compartilhadas. 
*   **Implicação para o Agente:** O chatbot não pode atuar com viés confirmatório de falsidade. Ele deve ser neutro na formulação da resposta e fornecer o contexto documental integral em vez de forçar um rótulo binário simplista.

### 2.2 Sazonalidade das Checagens e o Pico de 2018 (Gráfico 05 - FACTCKBR)
*   **Dado Empírico:** O volume de checagens salta de uma média de 10 checagens/mês em 2016 para mais de **150 checagens em um único mês (Outubro de 2018)**.
*   **Hipótese Explicativa:** A dinâmica eleitoral presidencial intensifica a disputa polarizada de narrativas e acelera a criação deliberada de campanhas de desinformação em redes sociais e aplicativos de mensagens, forçando as agências a mobilizarem plantões extraordinários de verificação.
*   **Implicação para o Agente:** A demanda sobre o chatbot será hiperconcentrada em janelas pré-eleitorais (agosto a outubro dos anos pares). As queries aos arquivos Parquet devem ser otimizadas para responder em milissegundos mesmo sob picos de tráfego.

### 2.3 Centralidade de Personagens e Temas Polarizados (Gráfico 07 - FACTCKBR)
*   **Dado Empírico:** **Jair Bolsonaro** concentra **25,1% (329)** e **Lula / PT** concentram **16,8% (220)** das alegações verificadas. Temas como a Previdência lideram os assuntos institucionais.
*   **Hipótese Explicativa:** A desinformação política gravita em torno de figuras carismáticas de liderança executiva que polarizam a atenção midiática e o algoritmo das plataformas sociais, servindo como "para-raios" de teorias conspiratórias.
*   **Implicação para o Agente:** É mandatória a resolução precisa de entidades (*Entity Matching*) para esses líderes e seus círculos próximos, prevenindo que homônimos ou apelidos distorçam as evidências do banco de dados.

### 2.4 Anomalia no `ratingValue` e Mascaramento de Nulos
*   **Dado Empírico:** Todos os 528 registros da Agência Lupa contêm `ratingValue = 4.0` e `reviewBody = "Empty"`.
*   **Hipótese Explicativa:** Falha de implementação no scraper do agregador original, que atribuiu um valor escalar padrão e falhou na captura do nó HTML da justificativa da Lupa.
*   **Implicação Técnica:** A normalização da variável alvo deve basear-se no texto do veredito (`alternativeName`), ignorando o campo numérico corrompido.

---

## 3. Eixo 1: Candidaturas, Patrimônio e Presença Digital (TSE 2022–2026)

A análise envolveu **514.167 candidatos**, **1.080.919 bens declarados** (somando **R$ 190,5 bilhões**) e **996.196 contas de redes sociais**.

### 3.1 Distribuição de Patrimônio e Hiperconcentração (Gráfico 01 - TSE)
*   **Dado Empírico:** A mediana de patrimônio de um candidato brasileiro é de **R$ 122.562,04**, enquanto a média é de **R$ 580.379,54** (distorcida pelo Top 1%, que declara mais de R$ 4,66 milhões). 25% dos candidatos declaram até R$ 32.000,00 e 5% declaram mais de R$ 1,4 milhão.
*   **Hipótese Explicativa:** O perfil patrimonial das candidaturas reflete a profunda desigualdade de renda e riqueza do Brasil. Candidaturas municipais de base representam a classe trabalhadora, enquanto candidaturas ao Senado e governos estaduais concentram membros das elites empresariais e latifundiárias tradicionais.
*   **Aplicação no Agente (`get_candidate_assets`):** O agente deve contextualizar alegações sobre patrimônio com base nos percentis populacionais: se um candidato declara R$ 800 mil, ele está no Top 10% de maior patrimônio de candidatos no país, mas distante do perfil de super-ricos.

### 3.2 Top Patrimônios e Outliers Estatísticos (Gráfico 02 - TSE)
*   **Dado Empírico:** Os maiores patrimônios em 2022 ultrapassam a faixa de centenas de milhões de reais, liderados por **Marcos Ermírio de Moraes (PSDB/GO - R$ 1,26 bilhão)** e **Paulo Octávio (PSD/DF - R$ 618,8 milhões)**.
*   **Hipótese Explicativa:** A legislação eleitoral permite autofinanciamento (limitado) e a presença de herdeiros de grandes conglomerados industriais ou do setor imobiliário nas eleições (especialmente como suplentes de senador ou governadores), visando proteção de interesses econômicos e prestígio político.
*   **Aplicação no Agente:** Detecção e alerta sobre candidaturas de suplência de senador, onde frequentemente figuram megaempresários financiadores com baixa visibilidade eleitoral direta.

### 3.3 Patrimônio vs. Sucesso Eleitoral (Gráfico 04 - TSE)
*   **Dado Empírico:** Deputados federais eleitos declararam em média **R$ 762.855,75**, contra **R$ 670.407,50** dos não eleitos (diferença moderada de 13,8%).
*   **Hipótese Explicativa:** A partir da proibição das doações empresariais (ADI 4650 em 2015), o fator determinante para a vitória eleitoral no Brasil deixou de ser a riqueza pessoal líquida do candidato e passou a ser o **acesso aos recursos bilionários do Fundo Especial de Financiamento de Campanha (FEFC)** distribuídos estrategicamente pelas cúpulas partidárias.
*   **Aplicação no Agente:** Esclarecer ao usuário que patrimônio próprio elevado não é garantia isolada de vitória nem condição obrigatória para se eleger deputado.

### 3.4 Resolução de Entidades: Viabilidade de 96,6% (Gráfico 05 - TSE)
*   **Dado Empírico:** O cruzamento determinístico dos **648 deputados federais da 57ª Legislatura** da Câmara com a base de candidaturas do TSE atingiu **96,6% de casamentos exatos (626 deputados)** por nome civil normalizado.
*   **Hipótese Explicativa:** Embora o CPF seja mascarado pela LGPD no TSE (`***123456**`) e omitido na Câmara, os nomes civis de parlamentares federais possuem baixa taxa de homonímia perfeita quando cruzados com a sigla do Estado de origem (UF).
*   **Aplicação no Agente:** Validação definitiva para a criação da tabela canônica dimensional `dim_politicos.parquet`, interligando mandatários e seus históricos de candidatura com garantia de precisão.

### 3.5 Hegemonia de Plataformas nas Redes Oficiais (Gráfico 06 - TSE)
*   **Dado Empírico:** Das 996.196 URLs registradas no TSE, **Instagram (44,9%)** e **Facebook (39,0%)** somam 83,9%. O TikTok alcança 4,4%, o YouTube 2,0% e o X (Twitter) apenas 1,6%.
*   **Hipótese Explicativa:** A comunicação política de massa no Brasil migrou para o ecossistema visual da Meta (Instagram/Facebook), que atinge a maior penetração demográfica no eleitorado geral. Plataformas de texto como o X possuem alcance de nicho (jornalistas e formadores de opinião), resultando em menor prioridade de homologação formal perante o TSE.
*   **Aplicação no Agente (`verify_official_social_media`):** Checagem contra perfis fakes que disseminam vídeos manipulados ou golpes de arrecadação financeira em nome de figuras políticas.

### 3.6 Bens Especiais Investigativos: Dinheiro Vivo e Crypto (Gráfico 07 - TSE)
*   **Dado Empírico:** **60.105 declarações somam R$ 2,08 bilhões em papel-moeda ("dinheiro vivo em espécie")**. 1.021 declarações declaram R$ 1,09 bilhão em criptoativos. O maior valor em espécie foi de R$ 39,56 milhões por um candidato no Pará.
*   **Hipótese Explicativa:** A declaração de grandes volumes de dinheiro em espécie guardado em residência é utilizada historicamente por agentes políticos para criar lastro tributário formal e justificar gastos eleitorais de rua não rastreáveis via sistema bancário, além de envolver economias regionais com baixa bancarização.
*   **Aplicação no Agente (`check_cash_and_special_assets`):** Verificação imediata de alegações de escândalos envolvendo "dinheiro em espécie na cueca/mala", confrontando com o que o político efetivamente declarou ao Estado.

---

## 4. Eixo 2: Gastos do Mandato e Cota Parlamentar (Câmara & Senado)

A análise cobriu **785.278 despesas da Câmara (CEAP)** somando **R$ 922,7 milhões**, **95.233 despesas do Senado (CEAPS)** somando **R$ 148,7 milhões**, e **5,21 milhões de contratos de campanha do TSE** (R$ 13,8 bilhões).

### 4.1 O Despencamento Eleitoral na Divulgação (Gráfico 01 - Gastos)
*   **Dado Empírico:** Em agosto e setembro de 2022, os gastos de **Divulgação da Atividade Parlamentar da Câmara despencaram 97,8%**, caindo de R$ 6,2 milhões/mês para apenas **R$ 135.898,73 em agosto** e **R$ 141.668,83 em setembro**, saltando para R$ 4,43M logo após as eleições em outubro. Em dezembro de todos os anos, ocorrem picos de R$ 15 milhões/mês.
*   **Hipótese Explicativa:** A queda vertical reflete o cumprimento do **Art. 73, VI, "b" da Lei das Eleições (Lei 9.504/97)**, que proíbe gastos de publicidade institucional nos 3 meses anteriores ao pleito. A Câmara suspende automaticamente os reembolsos de divulgação institucional para que não haja confusão com propaganda eleitoral. O pico de dezembro é o clássico esforço orçamentário para liquidar cotas anuais que não acumulam para o exercício seguinte.
*   **Aplicação no Agente (`check_parliamentary_expenses`):** Desmentir com provas cabais alegações de que deputados usaram a cota parlamentar para confeccionar panfletos de campanha em agosto/setembro de 2022.

### 4.2 Matriz de Destinação: Câmara vs. Senado (Gráfico 02 - Gastos)
*   **Dado Empírico:** Na Câmara, **Divulgação Parlamentar lidera com 43,5% (R$ 401,7M)**, seguida por Locação de Veículos (19,9%) e Manutenção de Escritório (15,7%). No Senado, **Consultorias Técnicas lideram com 24,1% (R$ 35,6M)**, seguidas por Locomoção/Combustíveis (23,2%) e Passagens (17,9%).
*   **Hipótese Explicativa:** O deputado federal precisa renovar constantemente sua visibilidade perante centenas de municípios para garantir sua reeleição proporcional a cada 4 anos, focando em autopromoção e marketing digital. O senador possui mandato de 8 anos, base estadual unificada e atua com maior foco em articulação institucional e análises legislativas complexas, demandando pareceres jurídicos e consultorias de alto custo.
*   **Aplicação no Agente:** Comparar os gastos de um parlamentar com o perfil característico da sua casa legislativa, identificando desvios de padrão.

### 4.3 Gastos Anuais e Tetos Diferenciados por UF (Gráfico 03 - Gastos)
*   **Dado Empírico:** Em 2023, a mediana de gasto anual da cota por deputado foi de **R$ 254.137,95**, o P90 foi de **R$ 466.054,42** e o valor máximo foi de **R$ 592.186,13** (Pompeo de Mattos - PDT/RS).
*   **Hipótese Explicativa:** O valor da CEAP não é uniforme no Brasil; a Mesa Diretora estipula tetos mais elevados para bancadas de estados geograficamente afastados de Brasília (ex: RR, AC, AM, RS), onde o custo das passagens aéreas e dos deslocamentos é substancialmente mais alto do que para parlamentares de Goiás ou do Distrito Federal.
*   **Aplicação no Agente:** Evitar conclusões errôneas de que parlamentares do Norte/Nordeste "gastam mais por descontrole", explicitando as diferenças regimentais por unidade federativa.

### 4.4 Fornecedores Híbridos: Mandato ↔ Campanha Eleitoral (Gráfico 04 - Gastos)
*   **Dado Empírico:** **35,17% dos fornecedores com CNPJ da Câmara (18.644 empresas)** também receberam pagamentos de campanhas eleitorais no TSE. Em **685 casos mapeados**, o *mesmo político* contratou no mandato exatamente a mesma empresa que havia contratado na sua campanha eleitoral (agências de publicidade, redes sociais, locadoras de veículos e gráficas).
*   *Nota Conceitual:* Os valores expressam o **faturamento bruto recebido com dinheiro público e partidário**, e não o lucro líquido da empresa.
*   **Hipótese Explicativa:** Existe um mercado consolidado de fornecedores especializados em prestar serviços a mandatos e campanhas políticas ("indústria da política"). Políticos tendem a manter relações de confiança estreita com fornecedores que executaram suas campanhas vitoriosas, contratando-os subsequentemente via cota de gabinete para manter a gestão de sua imagem e infraestrutura política regional.
*   **Aplicação no Agente (`cross_check_supplier_campaign`):** Rastrear se a contratação de uma empresa investigada pela imprensa é um fato isolado ou parte de uma cadeia contínua de recursos eleitorais e parlamentares.

### 4.5 Rastreabilidade de NF-e, Glosas e Voos de Ida (Gráfico 05 - Gastos)
*   **Dado Empírico:** **93,5% das notas da Câmara (734.544 despesas)** contêm link oficial (`urlDocumento`) para o espelho do comprovante fiscal. A fiscalização interna glosou **46.365 notas**, economizando **R$ 5,65 milhões** ao erário. As principais rotas de ida a partir de Brasília partem em direção a Belo Horizonte (544 voos), Salvador (494), Rio de Janeiro (333) e São Paulo (329).
*   **Hipótese Explicativa:** O sistema de transparência ativa da Câmara atingiu maturidade técnica com emissão eletrônica obrigatória. As glosas refletem mecanismos ativos de filtragem que barram itens não indenizáveis (como bebidas alcoólicas ou refeições fora do horário regimental). Os destinos aéreos refletem o fluxo semanal padrão de parlamentares retornando às maiores metrópoles e capitais de origem nas quintas e sextas-feiras.
*   **Aplicação no Agente (`get_expense_proof_document` e `check_glosa_history`):** Fornecer o link do PDF original da nota fiscal como evidência direta ao usuário e checar se alegações de gastos irregulares foram impedidas pela fiscalização da Casa.

---

## 5. Eixo 3: Atividade Legislativa, Autoria e Tramitação (Câmara & Senado)

A análise integrou **140.507 proposições da Câmara**, **456.351 vínculos de autoria** e **9.922 matérias do Senado Federal**.

### 5.1 A Taxonomia Real: Apenas 10% têm Força de Lei (Gráfico 01 - Legislativo)
*   **Dado Empírico:** **74,93% dos atos da Câmara (105.284)** são estritamente regimentais ou instrumentais (Pareceres de Relator PRL 13,85%, Requerimentos de Pauta RPD 11,05%, Requerimentos de Informação RIC 6,63%, Emendas EMC 6,3%, Indicações INC 3,72%). Proposições substantivas com força de lei (PL, PEC, PLP, MPV, PDL) representam **apenas 10,01% (14.071 atos)**.
*   **Hipótese Explicativa:** O processo legislativo exige uma engrenagem burocrática massiva de despachos, pareceres em comissões e requerimentos procedimentais para fazer andar qualquer matéria. Políticos se aproveitam do fato de que esses instrumentos recebem um número oficial de protocolo para alegar ao eleitorado que apresentaram "centenas de leis".
*   **Aplicação no Agente (`get_politician_legislative_summary`):** Desmascarar índices artificiais de produtividade parlamentar, informando ao usuário exatamente quantos atos eram **Projetos de Lei reais** e quantos eram simples votos de pesar ou requerimentos de audiência.

### 5.2 Autores Proponentes vs. Cosignatários em Bloco (Gráfico 02 - Legislativo)
*   **Dado Empírico:** Dos 411.537 vínculos de deputados, **71,7% (295.059)** são de Autores Principais (`proponente == 1`) e **28,3% (116.478)** são de Cosignatários de apoio. Quando consolidamos os mandatos por `idDeputadoAutor` (unificando mudanças de partido), os recordistas em apresentação de Projetos de Lei próprios são:
    1.  **Amom Mandel** (Cidadania / Republicanos - AM): **1.069 PLs/PECs**
    2.  **Duda Ramos** (MDB / Pode - RR): **983 PLs/PECs**
    3.  **Marcos Tavares** (PDT - RJ): **276 PLs**
    4.  **Jonas Donizette** (PSB - SP): **202 PLs**
    5.  **Alexandre Frota** (PROS / PSDB - SP): **156 PLs**
    Enquanto a lista de apoio/subscrição coletiva é liderada por articuladores partidários como **Sóstenes Cavalcante (735 apoios)** e **Raimundo Santos (602)**.
*   **Hipótese Explicativa:** Existem duas estratégias de atuação parlamentar opostas na Câmara: (1) deputados que utilizam assessorias jurídicas voltadas à produção industrial e protocolização em lote de minutas de PL para inflar suas métricas autorais de gabinete; e (2) líderes partidários e articuladores de frentes que focam em subscrever e articular requerimentos de urgência coletivos.
*   **Aplicação no Agente (`verify_proposition_authorship`):** Diferenciar com rigor se o político foi o criador do projeto ou se apenas assinou a lista de apoiadores para dar quórum regimental à bancada.

### 5.3 Mineração Temática: Temas que Mais Geram Desinformação (Gráfico 03 - Legislativo)
*   **Dado Empírico:** Entre os 12.146 projetos de lei e emendas constitucionais analisados:
    *   **Segurança Pública e Penal:** 1.122 projetos (9,24% de todos os PLs)
    *   **Tributos, Impostos e PIX:** 441 projetos (3,63%)
    *   **Tecnologia, Redes Sociais e IA:** 201 projetos (1,65%)
    *   **Armas, CACs e Desarmamento:** 149 projetos (1,23%)
    *   **Meio Ambiente e Marco Temporal:** 144 projetos (1,19%)
    *   **Drogas e Maconha:** 69 projetos (0,57%)
    *   **Saúde, Vacinas e Aborto:** 68 projetos (0,56%)
*   **Hipótese Explicativa:** Temas morais e de costumes (vacinas, aborto, armas) representam uma fração minúscula da produção legislativa real (<2%), mas respondem pela imensa maioria dos conteúdos virais de fact-checking nas redes sociais devido à alta carga emocional que mobiliza bases militantes.
*   **Aplicação no Agente (`search_legislative_propositions`):** Indexação semântica dedicada para esses temas, permitindo checar em segundos afirmações sensacionalistas do tipo *"projeto de lei quer proibir o PIX"* ou *"lei quer obrigar aborto"*.

### 5.4 O Funil de Efetividade: Menos de 2,5% Viram Lei (Gráfico 04 - Legislativo)
*   **Dado Empírico:** Apenas **2,42% das proposições da Câmara (3.407)** e **2,34% no Senado (232)** chegaram a ser transformadas em norma jurídica definitiva (`urnFinal` / `normaGerada`). No Senado, **mais de 75% das 9.922 matérias** permanecem paradas aguardando designação de relator ou na fase de relatório inicial.
*   **Hipótese Explicativa:** O modelo do presidencialismo de coalizão e as comissões permanentes funcionam como filtros institucionais de contenção. A vasta maioria dos projetos protocolados cumpre apenas a função de marcar posição política para a base eleitoral do parlamentar, sem intenção real de tramitação conclusiva.
*   **Aplicação no Agente (`get_proposition_status_and_pdf`):** Desmistificar a alegação recorrente de que propostas em tramitação inicial "já estão em vigor e devem ser cumpridas pela população".

### 5.5 Integridade Documental e Acesso à Íntegra em PDF (Gráfico 05 - Legislativo)
*   **Dado Empírico:** **99,6% das proposições da Câmara (139.905)** e **97,2% do Senado (9.643)** possuem link direto e funcional para o PDF oficial protocolado.
*   **Hipótese Explicativa:** A digitalização integral do processo legislativo pelo Sistema de Informações Legislativas (SILEG) e Senado Aberto garante a preservação do inteiro teor oficial em repositórios estáveis.
*   **Aplicação no Agente:** O chatbot pode entregar a íntegra oficial do documento como evidência definitiva, eliminando qualquer margem para dúvida ou contestação.

---

## 6. Matriz Consolidada de Padrões e Hipóteses de Fact-Checking

A tabela abaixo resume as hipóteses centrais confirmadas pela EDA e sua respectiva aplicação de auditoria:

| Eixo Analítico | Padrão Empírico Observado | Hipótese Causal & Regulatória | Aplicação no Chatbot Agêntico |
| :--- | :--- | :--- | :--- |
| **FACTCKBR** | 71,8% dos vereditos checados são Falsos e pico de checagens em out/2018. | Agências priorizam desmentir o dano social no auge da disputa eleitoral majoritária. | O Agente atua sem viés, fornecendo dados contextuais para desarmar a falsidade no momento da consulta. |
| **TSE (Bens)** | Mediana de R$ 122k vs Top 1% acima de R$ 4,6M; autofinanciamento bilionário. | Desigualdade de renda reproduzida na política e blindagem de interesses econômicos de elites. | Avalia o patrimônio relativo do candidato por percentil e alerta sobre suplentes bilionários. |
| **TSE (Especial)** | R$ 2,08 bi declarados em dinheiro vivo e R$ 1,09 bi em criptoativos. | Tentativa de lastro formal para recursos de campanha não rastreáveis via sistema bancário. | Checa declarações de dinheiro em espécie e aeronaves contra alegações de patrimônio oculto. |
| **TSE (Redes)** | 83,9% de concentração em Instagram e Facebook; X/Twitter com apenas 1,6%. | Prioridade eleitoral para plataformas com maior penetração demográfica visual de massa. | Verifica se contas que propagam discursos polarizados são perfis oficiais ou fakes. |
| **TSE / Câmara** | 96,6% de match determinístico entre deputados federais e dados do TSE 2022. | Baixa homonímia perfeita quando combinados Nome Civil Normalizado + UF de atuação. | Materialização da tabela dimensional `dim_politicos.parquet` para joins sem CPF. |
| **Gastos (CEAP)** | Queda de 97,8% nos gastos de divulgação em ago/set de 2022. | Proibição de publicidade institucional nos 3 meses pré-pleito (Art. 73 Lei 9.504/97). | Desmente alegações de campanha eleitoral bancada com cota de divulgação no auge do pleito. |
| **Gastos (Matriz)** | Câmara gasta 43,5% em divulgação; Senado gasta 47,3% em consultorias e locomoção. | Diferença de escopo: deputados dependem de marketing contínuo; senadores focam em articulação. | Compara o perfil do parlamentar com o comportamento médio esperado para sua respectiva Casa. |
| **Gastos (Rede)** | 35,2% de sobreposição com TSE; 685 casos de mesmo político e fornecedor. | Existência de uma indústria especializada de serviços que opera no mandato e na campanha. | Revela relações comerciais contínuas de parlamentares com agências de publicidade e locadoras. |
| **Gastos (NF-e)** | 93,5% das despesas com link direto e R$ 5,65 milhões economizados em glosas. | Maturidade da NF-e e fiscalização ativa das mesas diretoras contra gastos indevidos. | Exibe a URL do comprovante oficial da despesa e esclarece se valores foram rejeitados. |
| **Legislativo** | 74,9% dos atos são instrumentais; apenas 10% têm força de lei (PL/PEC). | Exigência burocrática de tramitação usada por políticos para inflar índices de produtividade. | Isola Projetos de Lei substantivos de simples votos de pesar e requerimentos protocolares. |
| **Legislativo** | 71,7% de autores principais vs 28,3% de apoiadores; Amom Mandel com 1.069 PLs. | Bipolaridade de estratégia: deputados de produção industrial em lote vs articuladores de bancada. | Determina se o político é o idealizador do projeto ou mero signatário de apoio em lista coletiva. |
| **Legislativo** | Apenas 2,4% dos projetos viram norma definitiva; >75% parados em comissões. | Filtro de contenção institucional do presidencialismo de coalizão contra projetos panfletários. | Desmente alegações de que projetos recém-apresentados já estão em vigor como lei obrigatória. |
| **Legislativo** | Mais de 97% de cobertura de PDFs originais digitalizados na Câmara e no Senado. | Transparência ativa e integração dos sistemas legislativos informatizados (SILEG). | Disponibiliza o link oficial da íntegra em PDF do projeto original assinado à Mesa. |

---

## 7. Catálogo Final de Ferramentas (Tools) do Chatbot Agêntico

Com base nos esquemas e filtros validados, define-se o catálogo completo de **17 ferramentas analíticas** do Chatbot:

### Módulo I: Checagem Eleitoral e Perfil (TSE)
1.  **`check_candidate_profile(nome, ano=2024, uf=None)`**: Retorna cargo, partido, situação do registro (deferido/indeferido) e dados sociodemográficos.
2.  **`get_candidate_assets(sq_candidato, ano)`**: Total declarado e lista dos 5 maiores bens discriminados.
3.  **`check_cash_and_special_assets(sq_candidato, ano)`**: Filtra exclusivamente dinheiro em espécie guardado em casa, aeronaves e criptoativos.
4.  **`verify_official_social_media(sq_candidato | nome)`**: Retorna a lista oficial de perfis e URLs homologados no TSE para validação de autenticidade.
5.  **`check_vote_destination_status(sq_candidato, ano)`**: Confirma se os votos foram válidos, nulos ou retidos *sub judice*.
6.  **`check_disqualification_motive(sq_candidato, ano)`**: Fundamento jurídico de impugnações ou cassações (Ficha Limpa, contas rejeitadas).

### Módulo II: Checagem de Gastos do Mandato e Cota (Câmara & Senado)
7.  **`check_parliamentary_expenses(parlamentar, casa, ano, categoria=None)`**: Total de despesas reembolsadas da cota, abertura por categoria e comparação com os percentis da Casa.
8.  **`get_top_suppliers_parliamentary(parlamentar, ano, top_n=5)`**: Ranking das empresas que mais receberam recursos da cota de gabinete do político.
9.  **`cross_check_supplier_campaign(cnpj_or_name, parlamentar)`**: Audita se uma empresa contratada pela cota do mandato também recebeu recursos da campanha eleitoral do político no TSE.
10. **`get_expense_proof_document(ide_documento | (parlamentar, data, valor))`**: Retorna a URL direta do comprovante digital / espelho da NF-e oficial.
11. **`check_flight_tickets_usage(parlamentar, ano)`**: Relação de passageiros beneficiados e rotas aéreas custeadas pela cota.
12. **`check_glosa_history(parlamentar, ano)`**: Histórico de notas fiscais questionadas ou rejeitadas pela fiscalização interna da Casa.

### Módulo III: Checagem de Atividade Legislativa e Autoria (Congresso)
13. **`search_legislative_propositions(termo_busca, sigla_tipo=None, ano=None, casa='camara')`**: Busca semântica por palavras-chave em ementas legislativas (ex: "porte de arma", "PIX", "aborto").
14. **`verify_proposition_authorship(numero, sigla_tipo, ano, politico)`**: Avalia se o parlamentar é o Autor Proponente (`proponente == 1`) ou apenas cosignatário secundário.
15. **`get_proposition_status_and_pdf(id_proposicao, casa='camara')`**: Retorna o status de tramitação (se foi arquivada, se está em comissão ou se virou lei) e o link do PDF original.
16. **`get_politician_legislative_summary(politico, ano, apenas_substantivos=True)`**: Reporta a produtividade legislativa real, separando Projetos de Lei de simples requerimentos regimentais.
17. **`check_bill_apensamentos(id_proposicao)`**: Informa se a matéria tramita de forma autônoma ou se está apensada a uma proposição principal mais antiga.

---

## 8. Próximos Passos de Engenharia

Com a conclusão integral da Análise Exploratória de Dados, o pipeline de dados está validado. As próximas etapas de desenvolvimento são:

1.  **Geração da Tabela Canônica de Entidades (`dim_politicos.parquet`):**
    *   Executar o script que materializa a resolução de entidades com 96,6% de match, associando `SQ_CANDIDATO` (TSE), `ideCadastro` (Câmara) e `COD_SENADOR` (Senado).
2.  **Implementação Modular das Tools em Python (`src/tools/`):**
    *   Implementar as funções em arquivos Python modulares (`tse_tools.py`, `gastos_tools.py`, `legislativo_tools.py`) que realizam varreduras otimizadas com Polars LazyFrame sobre os Parquets de `data/processed/`.
3.  **Integração do Agente com LLM (`src/core/agent.py`):**
    *   Conectar as assinaturas das tools ao cliente LLM existente ([src/core/llm_client.py](file:///Users/aluno2/PBIA/challenge1-grupo13/src/core/llm_client.py)) para permitir execução autônoma de fact-checking com respostas auditáveis e links de evidência primária.
