# Plano: cobertura das tools e confiabilidade do veredito

Origem: análise das fraquezas do agente em fact-checking político (09/10/2026), a partir da leitura de `src/tools/`, `src/services/tool_catalog.py`, `src/etl/build_parquet.py` e dos relatórios de EDA. Nada aqui foi medido por avaliação; os pontos vêm da leitura do código.

Regras do projeto valem em todas as fases: teste antes do código (regra 7), suíte por tool com caminho feliz, entidade não encontrada, ambígua e timeout mockado (regra 8), claim nova no golden só entra com tool correspondente (regra 5). Cobertura nova vai para um `golden_dataset_v2`; o v1 continua como portão de aceite.

## Diagnóstico resumido

- Só 8 tools chegam ao roteador. Tramitação, vetos e presença existem, mas não estão no catálogo do LLM.
- Voto individual de parlamentar e voto por partido não têm tool.
- TSE: a EDA especificou 6 tools (`check_candidate_profile`, `get_candidate_assets`, `check_cash_and_special_assets`, `verify_official_social_media`, `check_vote_destination_status`, `check_disqualification_motive`), mas a `tools_specification.md` foi dimensionada para as 30 claims do golden v1 e as cortou. O ETL já converte votação por município/zona, totalização presidencial e votação por seção de 2022, e nenhuma tool lê esses parquets.
- Base normativa com 12 tópicos e base de cobertura com 4 fontes, escritas à mão para o golden v1.
- `aprovado` na votação é heurística (`aprovacao == 1` ou "aprovad" na descrição). **Resolvido na Fase 0.**
- Os dados foram baixados à mão; não há rotina de atualização nem data da última carga. **Resolvido na Fase 0.5** (ingestão incremental de hora em hora na VM, com a data da base citada no veredito).

## Fase 0: correções de veredito (P)

1. `aprovado` passa a ser tri-estado (`True`, `False`, `None`). Só o campo `aprovacao` da API decide; o texto da descrição deixa de ser critério. `None` significa indeterminado e leva a INCONCLUSIVO.
2. O placar de votos conta tipos de voto não reconhecidos em `outros`, e o teste garante que a soma das opções é igual a `total`.
3. A presença continua inferida por diferença contra os deputados em exercício; o retorno deixa isso explícito (`ausentes_inferidos` e observação sobre suplentes e licenciados).

**Status (2026-10-10): concluída** (PR #52 mergeado; prompt do juiz em `production` no Langfuse).

## Fase 0.5: ingestão automática dos dados (M)

Hoje os CSVs são baixados à mão. A `origin/feat/webscraping` tem `scripts/download_public_datasets.py`, que baixa CEAP, cadastros, proposições e votações da Câmara e do Senado. A branch está muito atrás da `main` e não deve ser mergeada; traz-se só o script.

1. Trazer o script com `git show` e escrever os testes antes (rede mockada). Download parcial vira erro explícito.
2. Corrigir: verificação SSL ligada (o script a desliga, e as URLs funcionam com ela ligada), escrita em arquivo temporário seguida de renomeação, conferência contra `Content-Length`.
3. Manifesto declarativo versionado (fonte, ano, URL, destino, checksum), em vez de URLs fixas no código.
4. Cliente do TSE pela API CKAN (`dadosabertos.tse.jus.br/api/3/action/package_show?id=...`), que lista as URLs reais dos recursos. `resultados-2022` traz a totalização presidencial do 1º e do 2º turno em arquivos separados; candidatos, bens e prestação de contas respondem em `cdn.tse.jus.br`. O nome do recurso de redes sociais deve vir do CKAN, não de padrão adivinhado.
5. Fechar buracos: `senado/materias/materias.csv` (o ETL espera), proposições e votações além de 2024.
6. Encadear `download → build_parquet → dim_politicos` num comando, agendado na VM com lock, e gravar a data de cada carga para o juiz poder citá-la.
7. Cuidados: os arquivos do TSE são grandes (os 5 principais de 2022 somam cerca de 1,3 GB); conferir o disco da VM antes.

**Status (2026-10-10): concluída**, em produção na VM (PRs #53 a #58 e o da data da base). Uso, instalação e avisos em `docs/ingestion.md`.

| Passo | Entregue |
|---|---|
| 1 e 2 | Download seguro em `src/etl/download_datasets.py`: SSL ligado, `.part` + renomeação, `Content-Length`, `sha256` opcional, 3 tentativas com espera em erro transitório, extração de zip atômica. Rede mockada em todos os testes. |
| 3 | Manifesto `src/etl/datasets_manifest.json` (fontes de Câmara e Senado e regras do TSE), validado. Não há `sha256` fixo por fonte, porque os arquivos do governo mudam; o `sha256` real de cada carga fica no estado. |
| 4 | Cliente CKAN do TSE (`src/etl/tse_ckan.py`) para 2022 e 2026; os nomes de recurso vêm do CKAN. Recursos de `resultados-2026` ainda não publicados viram aviso, não falha. |
| 5 | `senado/materias` pelo serviço `/dadosabertos/processo` (o `materia/pesquisa/lista` está descontinuado) e os anos 2022 a 2026 de Câmara e Senado. |
| 6 | Pipeline `download → build_parquet → dim_politicos` (`src/etl/pipeline.py`) com lock, build em staging e publicação atômica, timer horário do systemd na VM, `ingestion_info.json` e `ingestion_status.json`. O veredito **cita a data da base** (`src/services/data_freshness.py`) quando a tool leu dados ingeridos. |
| 7 | Disco e memória da VM conferidos (61 GB, 36 GB livres; 7,8 GB de RAM); o build roda com limite de 4 GB. |

O que passou do plano:
- **Ingestão incremental**: `HEAD` por fonte (`ETag`, `Last-Modified` ou tamanho), com disjuntor por host lento. Novidade é de conteúdo (`sha256`), então fonte dinâmica com bytes idênticos não dispara rebuild.
- **Senado não dispara rebuild** (`"triggers_build": false` no manifesto): as matérias e a lista de senadores mudam quase toda hora. São baixadas e aguardam o próximo build disparado por Câmara ou TSE.
- **Estado e avisos**: `--status`, página `https://polis.software/status`, `GET /api/ingestion/status`, webhook (ntfy) e heartbeat (healthchecks.io).
- **Correções que a ingestão exigiu**: leitura em blocos de CSV grande (um de 4 GB derrubou a máquina de desenvolvimento), poda de colunas do TSE (`docs/data_schemas.md`), `ideCadastro` no CEAP, cadastro de senadores normalizado, `cod_senador` no `dim_politicos`, recarga do `PoliticianCache` quando o parquet muda.

Limitações conhecidas: as votações da Câmara são baixadas, mas não viram parquet (Fase 2); `camara/proposicoes` tem uma partição `ano=0` que vem do próprio CSV da Câmara; os parquets do Senado podem ficar algumas horas atrás da fonte; só há aviso de data para tools que leem parquet (as que consultam a API ao vivo ou a base normativa não têm).

Fora do escopo: `scrape_dados_abertos_tse` (raspagem de HTML, lê só 10 itens e não baixa) e `url_scraper.py` (artigos de notícia).

## Fase 1: tools do TSE (G)

1. Descoberta: abrir os parquets na VM e documentar o esquema em `docs/data_schemas.md` (turnos, cargos, anos, UFs). Confirmar se o 2º turno foi ingerido.
   **Passo 1 concluído (2026-10-10).** Esquema, domínios, sentinelas, chaves e homônimos documentados em `docs/data_schemas.md` seção 8, com o mapeamento proposto de cada tool para o parquet. Confirmado: o 2º turno de 2022 foi ingerido e os votos de presidente batem com o resultado oficial nos dois turnos; o TSE 2026 tem candidatos, bens, prestação de contas e redes sociais, mas `resultados-2026` ainda só tem PDFs (claims sobre o resultado de 2026 devem dar INCONCLUSIVO, regra 3). Achados que mudam as tools: `QT_VOTOS_NOMINAIS` inclui votos anulados (o resultado oficial é `QT_VOTOS_NOMINAIS_VALIDOS`); `despesas_pagas` só liga ao candidato via `SQ_PRESTADOR_CONTAS`; há 173 grupos de homônimos, 161 deles do mesmo partido; o `DS_CARGO` muda de caixa entre tabelas. A descoberta também achou e corrigiu um defeito no ETL: o `candidatos` perdia `NR_TURNO` (linhas do 2º turno duplicadas e indistinguíveis) e os campos de perfil.
2. Resultado: `get_election_result(cargo, ano, uf, turno)`, `get_candidate_votes(sq_candidato, ano, turno)`, `check_candidate_status` e `check_disqualification_motive`.
   **Passo 2 entregue em parte (2026-10-10):** `resolve_candidate`, `get_election_result` e `get_candidate_votes` (`src/tools/tse_tools.py`), no catálogo do roteador, com fonte TSE e data da base no veredito. `get_candidate_votes` resolve o nome por `resolve_candidate` no roteador e só então consulta (regra 2). Conferido com os parquets reais: 1º turno de 2022 LULA 57.259.504 e JAIR BOLSONARO 51.072.345 (118.229.719 válidos); 2º turno 60.345.999 e 58.206.354. Ano ou turno ausente, e 2026, devolvem evidência vazia com `status` (regra 3). **Passo 2 concluído** com `check_candidate_status` e `check_disqualification_motive` (situação por turno; motivos de `cassacao`, com aviso de que ausência de linha não prova regularidade; ambas resolvem o nome antes, sem exigir turno). O prompt do roteador no Langfuse (`production`) precisa ser atualizado com as regras novas.
3. Perfil e patrimônio: `check_candidate_profile`, `get_candidate_assets`, `check_cash_and_special_assets`, `verify_official_social_media`.
   **Passo 3 entregue (2026-10-10)** em `src/tools/tse_perfil_tools.py`, no catálogo do roteador (todas resolvem o nome antes, sem turno). Sem bem declarado não é patrimônio zero (aviso na evidência); "Não divulgável" e marcadores viram `None`; CPF, título, e-mail e data de nascimento não saem; redes sociais valem só para o que o candidato registrou no TSE (aceita `termo` para checar um perfil). Conferido com Lula e Bolsonaro 2022 e Lula 2026.
4. Finanças de campanha: totais de receitas e despesas por candidato.
   **Passo 4 entregue (2026-10-10)** em `src/tools/tse_financas_tools.py`: `get_campaign_finances` (receitas, despesas contratadas e pagas; a paga liga por `SQ_PRESTADOR_CONTAS`) e `get_top_campaign_finances` (ranking por cargo, receitas ou despesas contratadas). Cada candidato tem um só tipo de prestação e um só prestador no ano (conferido), então somar não duplica. Prestação não final (a de 2026 é parcial) traz aviso; sem prestação publicada não é gasto zero; nenhum doador ou fornecedor sai. Conferido: Lula 2022 receitas R$ 135.539.287,82 e despesas contratadas R$ 131.313.037,45; Presidente 2022 lidera Lula, Bolsonaro, Thronicke.
5. Guarda de especificidade: "primeiro turno" ou "a última eleição" sem ano vira INCONCLUSIVO (regra 3).
   **Passo 5 entregue (2026-10-10)** em `src/guardrails/actions.py` (`check_input_specificity`), antes de qualquer LLM ou tool: turno ordinal sem ano, "a última eleição"/"eleição passada", resultado eleitoral ("ganhou", "foi eleito") sem ano, e resultado futuro ("vai ganhar", "será eleito"), mesmo com ano. Não bloqueia regras e acesso a dados (golden 9 e 24), "deputado eleito" como descrição nem "PEC aprovada em primeiro turno" no plenário. A justificativa é a mesma para qualquer direção da claim (regra 6). Limite: é heurística de texto; claim sem as palavras-gatilho segue para as tools, que também recusam ano/turno ausentes.
6. Golden v2: ao menos 10 claims de TSE nos três vereditos, incluindo 2º turno e candidato ambíguo.
   **Passo 6 entregue (2026-10-10):** `golden_dataset_v2.json` = as 30 claims do v1 (inalteradas, testado) + 20 do TSE (ids 31 a 50, categoria `ELEICOES`): 8 VERDADEIRO, 6 FALSO, 6 INCONCLUSIVO (3 pela guarda, sem tool; 3 com tool e evidência vazia: 2026, "José Silva" ambíguo e candidato inexistente). Cada claim nova lista `expected_tools` do catálogo (regra 5, testado). Infra: `ELEICOES` em `ALLOWED_TOOLS`; `inconclusive_reason` (`evidencia_vazia` deixa a tool rodar se não trouxe evidência; sem ele continua exigindo nenhuma tool); dataset do Langfuse com o nome do arquivo. Resultado: `evaluation/baseline_v3.json`, 96% de `verdict_match`, os outros 4 scores em 100%, em duas rodadas seguidas. Erros que sobraram são os do v1 (#5 e #15, INCONCLUSIVO).
   **O que o golden v2 achou (e foi corrigido):** (a) a guarda de boatos bloqueava "redes sociais" mesmo como assunto; (b) em 2022 há dois "Pablo Marçal" (Presidente e Deputado Federal) e, com o cargo errado do LLM, o juiz deu FALSO sobre a candidatura errada: agora `cargo`/`uf`/`numero` que a claim não diz são descartados (`ground_candidate_args`) e o homônimo vira ambíguo; (c) o LLM escolhia `resolve_candidate` sozinha ou `resolve_politician` para candidato de eleição: descrição e prompt corrigidos. **Limite que existia:** o roteador faz uma tool por claim, então comparar dois candidatos nomeados não era suportado (as claims 35 e 42 foram escritas como ranking). Resolvido com  (abaixo).
7. Opcional: ampliar para 2018, 2020 e 2024 conforme o volume de dados.

## Fase 2: voto individual (M)

`get_member_vote(id_votacao, parlamentar)` e placar por partido, reaproveitando `/votacoes/{id}/votos`. Resolução do parlamentar antes (regra 2) e testes de timeout com mock.

## Fase 3: expor o que já existe (P)

Decidir se tramitação, vetos e presença entram no catálogo do roteador. Se entrarem, testar o roteamento e o limite de tools suportado pelo modelo local.

## Fase 4: cobertura e atualização (M)

- Rotina de atualização dos parquets: **entregue na Fase 0.5** (`docs/ingestion.md`).
- CEAP anterior a 2024 e parquets de matérias do Senado: **entregues na Fase 0.5** (CEAP e CEAPS de 2022 a 2026 e `senado/materias`).
- Base normativa com campos de vigência e data de revisão, e mais tópicos além dos 12 atuais.

## Fase 5: avaliação que mede de verdade (M)

- Conjunto de claims escrito por quem não viu as tools, nunca usado para desenvolver.
- Métricas por veredito e taxa de INCONCLUSIVO indevido.
- Teste de neutralidade com pares de claims espelhadas (regra 6).
- Rodar como experimento no Langfuse.

## Ordem

Fase 0, Fase 0.5, Fase 1 (descoberta primeiro), Fases 2 e 3 em paralelo, Fases 4 e 5 acompanhando desde a Fase 1.

**Onde estamos (2026-10-10):** Fases 0 e 0.5 concluídas; Fase 1, passo 1 (descoberta) concluído. **Comparação de candidatos (2026-10-10):**  () compara 2 a 4 candidatos em votos válidos (com turno), patrimônio, receitas ou despesas contratadas, numa chamada só. O roteador resolve cada nome antes (regra 2); um nome ambíguo ou desconhecido impede a comparação (INCONCLUSIVO); falta de dado de qualquer um é , nunca zero; empate não tem líder; disputas diferentes são avisadas; votos de 2026 dão "dados abertos não atualizados". O array de nomes é validado (2 a 4; aceita "A e B"). Golden v2 ganhou 11 claims de comparação (ids 51 a 61; 4 VERDADEIRO e 4 FALSO espelhados, 3 INCONCLUSIVO): 61 claims,  96,7% em duas rodadas, demais scores em 100% (). Limite que fica: comparar métricas de tipos diferentes, ou mais de 4 candidatos, não é suportado; a execução de várias tools por claim (opção B) fica para a Fase 3.

Passos 1 a 6 concluídos (item 7, ampliar para outros anos, é opcional). Próximo: Fases 2 a 5; a 5 deve incluir claims de comparação entre candidatos se o roteador passar a encadear tools.
