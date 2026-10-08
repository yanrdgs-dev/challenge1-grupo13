# Especificação de Tools do Agente de Fact-Checking

- **Documento:** `docs/tools_specification.md`
- **Projeto:** Verificação de Fake News Política & Desinformação (CBL - Grupo 13)
- **Escopo:** Catálogo de tools (function-calling) do sistema multiagente de fact-checking, dimensionado para cobrir 100% das claims de `golden_dataset_v1.json`
- **Status:** Especificação — **nenhuma implementação de código nesta etapa**

---

## 1. Visão Geral

O sistema é dividido em dois agentes:

1. **Agente Roteador/Extrator** — recebe a claim do usuário, decompõe em sub-alegações quando necessário, extrai entidades (parlamentar, proposição, categoria de gasto, ano) e decide quais tools chamar, com quais parâmetros.
2. **Agente Sintetizador** — recebe os retornos estruturados das tools chamadas + a claim original e produz o veredito final (`VERDADEIRO` / `FALSO` / `INCONCLUSIVO`) citando a evidência primária.

As tools estão organizadas em 5 grupos, conforme a natureza da fonte de dado:

| Grupo | Natureza | Rede? |
|---|---|---|
| Resolução de Entidade | lookup local / API | tool 1 local, tool 2 via API |
| Gastos | dado local já ingerido (CEAP/CEAPS) | não |
| Legislativo | dado local já ingerido (proposições) | não |
| Votações | **API ao vivo** (Câmara/Senado) — decisão do time: não será feita ingestão em Parquet para este eixo | sim |
| Regras institucionais / disponibilidade de dado | base de conhecimento curada manualmente | não |

**Legenda de status de implementação:**
- 🟢 Pronta para codificar — dado local já existe em `data/processed/`
- 🟡 Pronta para codificar — endpoint de API conhecido e documentado
- 🔴 Requer validação de endpoint antes de codificar
- ⚪ Requer curadoria de conteúdo (não é acesso a dado externo, é uma tabela de conhecimento a popular)

---

## 2. Grupo: Resolução de Entidade

### 2.1 `resolve_politician` 🟢 (Implementada ✅)

- **Status de Implementação:** ✅ Concluída em `src/tools/resolve_politician.py`
- **Suíte de Testes:** `tests/test_resolve_politician.py` (20/20 testes unitários passando)
- **Tabela Dimensional:** `data/processed/dim_politicos.parquet`

**Parâmetros**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `nome_busca` | `str` | Sim | Nome civil, nome de urna ou apelido citado na claim |
| `uf` | `str` | Não | Sigla da UF, usada para desambiguar homônimos |
| `cargo` | `str` | Não | `"Deputado Federal"` \| `"Senador"` |
| `ano` | `int` | Não | Ano/legislatura de referência do mandato |

**Quando usar:** sempre que o Agente Roteador identificar um nome próprio de parlamentar na claim, antes de qualquer outra tool que exija um ID de parlamentar. No golden dataset é usada em modo de **validação**, não de filtro de entrada: depois que `get_top_ceap_spender` (id 1) retorna um nome, `resolve_politician` confirma que não é homônimo antes do sintetizador aceitar o match.

**O que faz:** normaliza o texto (remoção de acento, caixa, apelidos de urna) e resolve para o registro canônico da tabela dimensional de políticos, retornando os IDs de junção de cada base de origem.

**Retorno:** `{sq_candidato, ideCadastro, cod_senador, nome_civil, nome_urna, casa, uf, partido, ambiguous, candidatos_alternativos[]}`

**Modo de implementação:** lookup em memória sobre `dim_politicos.parquet` (tabela canônica já planejada na EDA de Candidaturas, unificando `SQ_CANDIDATO` do TSE, `ideCadastro` da Câmara e `COD_SENADOR` do Senado por nome normalizado + UF). Fuzzy matching via RapidFuzz com threshold configurável. Sem chamada de rede.

---

### 2.2 `resolve_proposition` 🟢 (Implementada ✅)

- **Status de Implementação:** ✅ Concluída em `src/tools/resolve_proposition.py`
- **Cliente HTTP Especializado:** `src/tools/legislative_client.py` (timeout estrito 5.0s, cache de sessão em memória)
- **Suíte de Testes:** `tests/test_resolve_proposition.py` (10/10 testes passando) e `tests/test_legislative_client.py` (7/7 testes passando)
- **Contrato JSON Schema:** `specs/002-resolve-proposition/contracts/resolve_proposition.json`

**Parâmetros**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `casa` | `str` | Sim | `"camara"` \| `"senado"` \| `"congresso"` |
| `sigla_tipo` | `str` | Não | `"PL"`, `"PEC"`, `"MPV"`, `"PDL"` etc. — quando a claim cita a matéria formalmente |
| `numero` | `int` | Não | Número da proposição |
| `ano` | `int` | Não | Ano de apresentação |
| `termo_busca` | `str` | Não | Texto livre (nome popular da lei, tema) quando não há número formal |

**Quando usar:** sempre que a claim mencionar uma proposição/votação específica, com ou sem número formal, antes de chamar qualquer tool de votação. Golden dataset: ids 4, 5, 15, 18, 26, 28, 30.

**O que faz:** identifica a proposição via match exato (quando `sigla_tipo`+`numero`+`ano` são informados) ou via busca textual na ementa (quando só há `termo_busca`). Quando a busca textual retorna múltiplos candidatos sem desambiguação clara, retorna a lista inteira com `ambiguous=True` — sinal que o roteador usa para decidir por `INCONCLUSIVO` (ids 26, 30).

**Retorno:** `{id_proposicao, sigla_tipo, numero, ano, ementa, casa, ambiguous, candidatos[]}`

**Modo de implementação:** chamada HTTP GET à API de Dados Abertos (Câmara: `dadosabertos.camara.leg.br/api/v2/proposicoes`; Senado: `legis.senado.leg.br/dadosabertos`). Match exato via parâmetros de query nativos da API; busca textual usando o parâmetro de palavras-chave da própria API, refinada com fuzzy match local sobre a ementa retornada. Cliente HTTP com timeout curto (~5s) e cache em memória por chave de busca durante a sessão da claim.

---

## 3. Grupo: Gastos (dado local — CEAP/CEAPS)

### 3.1 `get_top_ceap_spender` 🟢

**Parâmetros**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `casa` | `str` | Sim | `"camara"` \| `"senado"` |
| `ano` | `int` | Sim | Ano de referência |
| `top_n` | `int` | Não (default `1`) | Quantidade de posições no ranking |

**Quando usar:** claims de ranking/superlativo sobre gasto de cota ("quem mais gastou"). Golden dataset: id 1.

**O que faz:** agrega o total de reembolsos de cota por parlamentar no ano informado e retorna os `top_n` maiores gastadores, com nome, UF, partido e valor total.

**Retorno:** `[{nome_parlamentar, uf, partido, valor_total, posicao}]`

**Modo de implementação:** consulta analítica local (Polars `LazyFrame` ou DuckDB `read_only=True`, conforme padrão já definido em `docs/data_schemas.md`) sobre `data/processed/camara/ceap` ou `data/processed/senado/ceaps`; `group_by(idDeputado/idSenador).agg(sum(vlrLiquido))`, ordenação decrescente, `head(top_n)`. Sem chamada de rede.

---

### 3.2 `list_expense_categories` 🟢

**Parâmetros**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `casa` | `str` | Sim | `"camara"` \| `"senado"` |
| `incluir_exemplos` | `bool` | Não (default `True`) | Se deve retornar amostra de fornecedores/valores por categoria |

**Quando usar:** claims sobre elegibilidade de uma categoria de despesa ("pode/não pode usar a cota para X"). Golden dataset: ids 2, 11, 16, 17, 22.

**O que faz:** retorna as categorias de despesa (`txtDescricao`) efetivamente presentes nos dados históricos da casa informada, com contagem de lançamentos — evidência empírica de uso real, não apenas de permissão teórica.

**Retorno:** `[{categoria, qtd_lancamentos, valor_total, exemplos[]}]`

**Modo de implementação:** `distinct()` + agregação de contagem/soma sobre a coluna de categoria do parquet de CEAP/CEAPS via Polars/DuckDB. Execução 100% local, sem rede.

---

### 3.3 `check_parliamentary_expenses` 🟢

**Parâmetros**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `casa` | `str` | Sim | `"camara"` \| `"senado"` |
| `ano` | `int` | Sim | Ano de referência |
| `categoria` | `str` | Não | Filtro por categoria de despesa |
| `parlamentar_id` | `str` | Não | ID resolvido via `resolve_politician`; se omitido, agrega todos os parlamentares |

**Quando usar:** quando a claim exige um valor real ou comparação contra um limite numérico alegado. Golden dataset: id 13 (checar se existem lançamentos de combustível acima de R$ 500/ano, refutando um teto fixo alegado).

**O que faz:** retorna lançamentos (ou agregados min/max/média) filtrados por casa/ano/categoria/parlamentar.

**Retorno:** `{filtros_aplicados, valor_min, valor_max, valor_medio, qtd_lancamentos, amostra[]}`

**Modo de implementação:** `filter()` + agregação sobre o parquet de CEAP/CEAPS via Polars/DuckDB. Local, sem rede.

---

## 4. Grupo: Legislativo (dado local — proposições)

### 4.1 `get_proposition_tramitation_history` 🟢

**Parâmetros**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `casa` | `str` | Sim | `"camara"` \| `"senado"` |
| `id_proposicao` | `str` | Sim | ID resolvido via `resolve_proposition` ou já conhecido do dado local |

**Quando usar:** claims sobre o processo legislativo de uma proposição concreta (passagem por comissões, apensamentos). Golden dataset: id 18 (checar amostra de PLs aprovados e confirmar passagem por comissão temática).

**O que faz:** retorna a sequência de despachos/órgãos pelos quais a proposição tramitou, incluindo se passou por comissões temáticas antes do plenário e se está apensada a outra matéria.

**Retorno:** `{tramitacao: [{data, orgao, despacho}], proposicao_principal}`

**Modo de implementação:** leitura do parquet local `data/processed/camara/proposicoes` (+ `proposicoes_autores` se necessário para contexto de autoria) — dado já ingerido no Eixo 3 da EDA. Sem chamada de rede.

---

## 5. Grupo: Votações (API ao vivo)

> Decisão de arquitetura: este eixo **não terá ETL/Parquet próprio**. As tools abaixo consultam a API de Dados Abertos da Câmara e do Senado em tempo de execução.

### 5.1 `get_proposition_vote_result` 🟡

**Parâmetros**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id_proposicao` | `str` | Sim | Retornado por `resolve_proposition` |
| `casa` | `str` | Sim | `"camara"` \| `"senado"` |
| `tipo_votacao` | `str` | Não | Ex.: `"urgência"`, `"texto-base"`, `"aprovação"` — filtro sobre os eventos retornados |

**Quando usar:** claim afirma que uma proposição específica foi (ou não) aprovada/votada. Golden dataset: ids 4, 5, 28.

**O que faz:** consulta os eventos de votação da proposição na API da casa informada e retorna a lista de votações, com data, tipo e resultado (aprovado/rejeitado). Lista vazia significa que a proposição ainda não foi votada — esse é justamente o sinal usado para o id 28 (claim sobre votação futura/"em breve"), que resulta em `INCONCLUSIVO` por ausência de evento, não por erro.

**Retorno:** `[{id_votacao, data, tipo_votacao, aprovado: bool}]`

**Modo de implementação:** HTTP GET (Câmara: `/proposicoes/{id}/votacoes`; Senado: endpoint equivalente de matérias/votações). Timeout curto e retry com backoff; resultado cacheado por `id_proposicao` durante a sessão da claim para evitar refetch entre sub-claims.

---

### 5.2 `get_proposition_vote_breakdown` 🟡

**Parâmetros**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id_votacao` | `str` | Sim | Obtido em `get_proposition_vote_result` |
| `casa` | `str` | Sim | `"camara"` \| `"senado"` |

**Quando usar:** claim faz afirmação sobre unanimidade ou distribuição de votos de uma votação nominal específica. Golden dataset: id 15 (Marco Temporal — refutar "sem nenhum voto contra").

**O que faz:** retorna a contagem de votos por opção (Sim / Não / Abstenção / Obstrução / Ausente) para a votação informada.

**Retorno:** `{sim, nao, abstencao, obstrucao, ausente, total}`

**Modo de implementação:** HTTP GET (Câmara: `/votacoes/{id}/votos`, agregado no cliente; Senado: endpoint equivalente), reaproveitando o mesmo client HTTP (timeout/retry/cache) de 5.1.

---

### 5.3 `get_congress_veto_sessions` 🟡 *(validado em 29/09/2026)*

**Parâmetros**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `ano` | `int` | Sim | Ano de referência do veto |
| `codigo_veto` | `str` | Não | Código do veto (`Veto.Codigo`), quando já conhecido, para buscar o resultado detalhado direto |

**Quando usar:** claim nega a existência histórica de votação de veto presidencial. Golden dataset: id 20.

**O que faz:** lista os vetos de um ano e, para cada um, o resultado da votação nominal em sessão conjunta do Congresso Nacional (mantido/derrubado por dispositivo), com data da sessão e link do PDF oficial do resultado.

**Retorno:** `[{codigo_veto, numero, ano, em_tramitacao, data_sessao_conjunta, dispositivos: [{descricao, situacao, tipo_votacao}], url_pdf_resultado}]`

**Modo de implementação — validado via chamada real à API do Senado:**
- `GET https://legis.senado.leg.br/dadosabertos/materia/vetos/{ano}` → lista de vetos do ano, com `Codigo`, `Materia`, `EmTramitacao`. Testado com `ano=2023`: retornou 49 vetos reais (HTTP 200, segue redirect 301→200).
- `GET https://legis.senado.leg.br/dadosabertos/plenario/resultado/veto/{codigo}` → resultado nominal por dispositivo. Testado com `codigo=16269`: retornou `PdfsResultadoVotacao` referenciando **"Resultado da cédula apurada na Sessão Conjunta em 09/05/2024"** e `Dispositivo.Situacao: "Rejeitado"`, `PossuiVotos: "Sim"`, `TipoVotacao: "Cédula"` — confirma que o dado é público, estruturado e explicita que a votação ocorre em **sessão conjunta do Congresso Nacional** (da qual o Senado participa), o que já sustenta sozinho o veredito FALSO do id 20.
- Endpoints descobertos via OpenAPI spec real em `https://legis.senado.leg.br/dadosabertos/v3/api-docs` (path `/dadosabertos/materia/vetos/{ano}` e `/dadosabertos/plenario/resultado/veto/{codigo}`), não documentados de forma legível na página de portal HTML.
- Client HTTP deve seguir redirects (`-L`), pois o domínio raiz responde com 301 antes de resolver.

---

### 5.4 `get_plenary_attendance` 🟡 *(validado em 29/09/2026 — Câmara confirmada; Senado parcial)*

**Parâmetros**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `casa` | `str` | Sim | `"camara"` \| `"senado"` |
| `id_evento` | `str` | Sim (Câmara) | ID da sessão deliberativa, obtido via busca de eventos por período |
| `parlamentar_id` | `str` | Não | ID resolvido via `resolve_politician`, para filtrar um único parlamentar no resultado |
| `periodo` | `str` | Sim | Intervalo de datas, usado para localizar o(s) evento(s) quando `id_evento` não é informado |

**Quando usar:** claim sobre disponibilidade de consulta de faltas em plenário. Golden dataset: id 7.

**O que faz:** para a Câmara, retorna a lista de deputados que registraram presença numa sessão deliberativa específica; a ausência é inferida por diferença contra o quadro completo de deputados em exercício (`/deputados`) na mesma legislatura.

**Retorno:** `{id_evento, data, presentes: [{id_deputado, nome, uf, partido}], ausentes_inferidos: [...]}`

**Modo de implementação — validado via chamada real à API da Câmara:**
- `GET /api/v2/referencias/eventos/codTipoEvento` → confirma código `110` = "Sessão Deliberativa".
- `GET /api/v2/eventos?codTipoEvento=110&dataInicio=AAAA-MM-DD&dataFim=AAAA-MM-DD` → localiza sessões plenárias reais (testado com junho/2024: retornou sessões com `orgaos.sigla = "PLEN"`, ex. evento `id=73216`).
- `GET /api/v2/eventos/{id}/deputados` → **testado com `id=73216`: retornou 474 deputados** (de ~513 em exercício), confirmando que o endpoint lista quem **registrou presença** naquela sessão — a diferença contra o total de deputados em exercício dá a lista de ausentes, respondendo diretamente ao id 7.
- Senado: a API de Dados Abertos (`v3/api-docs`) não expõe um endpoint dedicado de presença/frequência individual fora do contexto de votações nominais (onde o status "Ausente"/"Não votou" aparece por votação, não como registro de frequência geral). Como o id 7 tem `target_entity = "Câmara dos Deputados"`, isso não bloqueia o golden dataset v1; fica registrado como limitação para eventuais claims futuras sobre frequência de senadores.

---

## 6. Grupo: Regras Institucionais e Disponibilidade de Dados (base curada)

Estas duas tools **não consultam API nem dataset transacional** — respondem a partir de uma base de conhecimento pequena, curada manualmente uma única vez a partir de fontes normativas primárias. Nenhuma claim de regra/procedimento do golden dataset é respondida "adivinhando" a partir de dado bruto.

### 6.1 `check_institutional_rule` ⚪

**Parâmetros**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `topico` | `str` | Sim | Chave fechada (enum) — ver lista abaixo |

**Enum de tópicos necessários para o golden dataset v1:**
`calculo_cota_por_uf`, `sabatina_stf`, `votacao_simbolica`, `teto_categoria_combustivel`, `prestacao_contas_partido`, `veto_presidencial`, `lai_gratuidade`, `cota_campanha_vs_mandato`, `teto_gastos_campanha`, `cota_compra_bens`, `tramitacao_comissoes`

**Quando usar:** claim descreve uma norma/regra/procedimento institucional que não pode ser respondida apenas com dado transacional. Golden dataset: ids 6, 10, 12, 13 (complemento), 16 (reforço), 19, 20, 21, 22 (reforço), 24.

**O que faz:** retorna o resumo da norma aplicável ao tópico, a fonte legal/regimental (artigo, resolução, lei) e o veredito de regra (permitido / proibido / procedimento descrito).

**Retorno:** `{topico, resposta_resumida, fonte_normativa, fundamentacao}`

**Modo de implementação:** tabela curada manualmente (ex.: arquivo YAML/JSON versionado em `src/tools/knowledge/institutional_rules.yaml`), populada a partir do Regimento Interno da Câmara, Regimento Interno do Senado, Resolução CEAP (Câmara), Resolução CEAPS (Senado), Lei nº 9.096/1995 (Lei dos Partidos), Lei nº 12.527/2011 (LAI) e Lei nº 9.504/1997 (Lei das Eleições). Cada entrada do enum vira uma linha dessa tabela, com citação da fonte. A tool em si é apenas um lookup por chave — sem busca semântica nesta primeira versão (evolução futura possível para RAG se o enum crescer muito).

---

### 6.2 `check_data_source_coverage` ⚪

**Parâmetros**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `fonte` | `str` | Sim | Enum: `portal_transparencia` \| `tse_prestacao_contas` \| `camara_frequencia` \| `camara_notas_taquigraficas` |
| `tipo_dado` | `str` | Sim | Texto curto identificando o recorte, ex.: `"diarias_passagens_ministerios"` |

**Quando usar:** claim pergunta se um tipo de dado é (ou não) publicamente consultável em um portal, sem pedir o valor em si. Golden dataset: ids 3, 7 (fallback caso `get_plenary_attendance` não seja viável), 8, 9, 14, 21 (reforço), 23.

**O que faz:** confirma se o recorte de dado é exposto publicamente pela fonte informada, com URL/endpoint de referência e a base legal de obrigatoriedade (LAI, decisão do STF, etc.).

**Retorno:** `{fonte, tipo_dado, disponivel: bool, url_referencia, observacao}`

**Modo de implementação:** mesma natureza da tool 6.1 — tabela curada manualmente, já que a maioria dessas fontes (Portal da Transparência/CGU, frequência legislativa) está fora do escopo atual de ingestão do projeto (que cobre apenas TSE, Câmara e Senado). Cada entrada documenta manualmente o que a fonte expõe e desde quando.

---

## 7. Lógica sem tool: guarda de especificidade do Agente Roteador

Não é uma tool chamável — é uma regra de pré-checagem que o Agente Roteador aplica **antes** de decidir chamar qualquer tool, para evitar inventar parâmetros a partir de uma claim subespecificada.

**Critérios de bloqueio (qualquer um já basta para `INCONCLUSIVO` sem tool call):**
- (a) nenhuma entidade nomeada resolvível na claim (ex.: `"um deputado"`, `"um senador"`, sem nome próprio);
- (b) referência temporal relativa não ancorável (`"recentemente"`, `"ano passado"`, `"em breve"`);
- (c) fonte de baixa credibilidade citada na própria claim (`"nas redes sociais estão dizendo"`, `"segundo comentários na imprensa"`, `"teria"`);
- (d) `resolve_proposition` retorna múltiplos candidatos ambíguos sem forma de desambiguar pelo texto da claim.

**Golden dataset cobertos por este critério:** ids 25, 27, 29 (bloqueio direto, critérios a/b/c — nenhuma tool chamada) e ids 26, 30 (critério d, após tentativa de `resolve_proposition`). O id 28 é um caso híbrido: tem entidade parcialmente resolvível (tema "inteligência artificial"), então a tool é chamada e o próprio retorno vazio de `get_proposition_vote_result` sustenta o `INCONCLUSIVO`, em vez do bloqueio prévio.

---

## 8. Matriz de Cobertura do Golden Dataset v1

| ID | Categoria | Veredito esperado | Tool(s) principais |
|---|---|---|---|
| 1 | GASTOS | VERDADEIRO | `get_top_ceap_spender` → `resolve_politician` |
| 2 | GASTOS | VERDADEIRO | `list_expense_categories` |
| 3 | GASTOS | VERDADEIRO | `check_data_source_coverage` |
| 4 | VOTACOES | VERDADEIRO | `resolve_proposition` → `get_proposition_vote_result` |
| 5 | VOTACOES | VERDADEIRO | `resolve_proposition` → `get_proposition_vote_result` |
| 6 | GASTOS | VERDADEIRO | `check_institutional_rule` (`calculo_cota_por_uf`) |
| 7 | VOTACOES | VERDADEIRO | `get_plenary_attendance` (validada) |
| 8 | GASTOS | VERDADEIRO | `check_data_source_coverage` |
| 9 | GASTOS | VERDADEIRO | `check_data_source_coverage` |
| 10 | VOTACOES | VERDADEIRO | `check_institutional_rule` (`sabatina_stf`) |
| 11 | GASTOS | VERDADEIRO | `list_expense_categories` |
| 12 | VOTACOES | VERDADEIRO | `check_institutional_rule` (`votacao_simbolica`) |
| 13 | GASTOS | FALSO | `check_institutional_rule` (`teto_categoria_combustivel`) + `check_parliamentary_expenses` |
| 14 | GASTOS | FALSO | `check_data_source_coverage` |
| 15 | VOTACOES | FALSO | `resolve_proposition` → `get_proposition_vote_breakdown` |
| 16 | GASTOS | FALSO | `list_expense_categories` + `check_institutional_rule` (`cota_compra_bens`) |
| 17 | GASTOS | FALSO | `list_expense_categories` |
| 18 | VOTACOES | FALSO | `get_proposition_tramitation_history` + `check_institutional_rule` (`tramitacao_comissoes`) |
| 19 | GASTOS | FALSO | `check_institutional_rule` (`prestacao_contas_partido`) |
| 20 | VOTACOES | FALSO | `get_congress_veto_sessions` (validada) + `check_institutional_rule` (`veto_presidencial`) |
| 21 | GASTOS | FALSO | `check_institutional_rule` (`lai_gratuidade`) |
| 22 | GASTOS | FALSO | `check_institutional_rule` (`cota_campanha_vs_mandato`) + `list_expense_categories` |
| 23 | VOTACOES | FALSO | `check_data_source_coverage` |
| 24 | GASTOS | FALSO | `check_institutional_rule` (`teto_gastos_campanha`) |
| 25 | GASTOS | INCONCLUSIVO | nenhuma — guarda do roteador |
| 26 | VOTACOES | INCONCLUSIVO | `resolve_proposition` (ambíguo) — guarda do roteador |
| 27 | GASTOS | INCONCLUSIVO | nenhuma — guarda do roteador |
| 28 | VOTACOES | INCONCLUSIVO | `resolve_proposition` → `get_proposition_vote_result` (vazio) |
| 29 | GASTOS | INCONCLUSIVO | nenhuma — guarda do roteador |
| 30 | VOTACOES | INCONCLUSIVO | `resolve_proposition` (ambíguo/sem match confiável) — guarda do roteador |

---

## 9. Próximos Passos

1. ~~Validar os dois endpoints marcados 🔴~~ — **concluído em 29/09/2026**: `get_congress_veto_sessions` e `get_plenary_attendance` têm endpoint real confirmado por chamada HTTP direta (ver seções 5.3 e 5.4). Todo o catálogo agora é 🟢/🟡 (sem itens bloqueados por dado). Único ponto em aberto: Senado não tem endpoint dedicado de frequência individual fora de votações nominais — sem impacto no golden dataset v1 (id 7 é sobre a Câmara).
2. Popular as tabelas curadas de `check_institutional_rule` (11 tópicos) e `check_data_source_coverage` (4 fontes) com citação de fonte primária.
3. Implementar os módulos em `src/tools/` (`entity_tools.py`, `gastos_tools.py`, `legislativo_tools.py`, `votacoes_api.py`, `knowledge_tools.py`), incluindo client HTTP compartilhado com timeout, retry e cache por sessão de claim (usado por `resolve_proposition`, `get_proposition_vote_result`, `get_proposition_vote_breakdown`, `get_congress_veto_sessions`, `get_plenary_attendance`) — lembrar de seguir redirects (`-L`), pois `legis.senado.leg.br` responde 301 no domínio raiz antes de resolver o recurso.
