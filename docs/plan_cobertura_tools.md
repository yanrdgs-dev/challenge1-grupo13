# Plano: cobertura das tools e confiabilidade do veredito

Origem: análise das fraquezas do agente em fact-checking político (09/10/2026), a partir da leitura de `src/tools/`, `src/services/tool_catalog.py`, `src/etl/build_parquet.py` e dos relatórios de EDA. Nada aqui foi medido por avaliação; os pontos vêm da leitura do código.

Regras do projeto valem em todas as fases: teste antes do código (regra 7), suíte por tool com caminho feliz, entidade não encontrada, ambígua e timeout mockado (regra 8), claim nova no golden só entra com tool correspondente (regra 5). Cobertura nova vai para um `golden_dataset_v2`; o v1 continua como portão de aceite.

## Diagnóstico resumido

- Só 8 tools chegam ao roteador. Tramitação, vetos e presença existem, mas não estão no catálogo do LLM.
- Voto individual de parlamentar e voto por partido não têm tool.
- TSE: a EDA especificou 6 tools (`check_candidate_profile`, `get_candidate_assets`, `check_cash_and_special_assets`, `verify_official_social_media`, `check_vote_destination_status`, `check_disqualification_motive`), mas a `tools_specification.md` foi dimensionada para as 30 claims do golden v1 e as cortou. O ETL já converte votação por município/zona, totalização presidencial e votação por seção de 2022, e nenhuma tool lê esses parquets.
- Base normativa com 12 tópicos e base de cobertura com 4 fontes, escritas à mão para o golden v1.
- `aprovado` na votação é heurística (`aprovacao == 1` ou "aprovad" na descrição).
- Os dados foram baixados à mão; não há rotina de atualização nem data da última carga.

## Fase 0: correções de veredito (P)

1. `aprovado` passa a ser tri-estado (`True`, `False`, `None`). Só o campo `aprovacao` da API decide; o texto da descrição deixa de ser critério. `None` significa indeterminado e leva a INCONCLUSIVO.
2. O placar de votos conta tipos de voto não reconhecidos em `outros`, e o teste garante que a soma das opções é igual a `total`.
3. A presença continua inferida por diferença contra os deputados em exercício; o retorno deixa isso explícito (`ausentes_inferidos` e observação sobre suplentes e licenciados).

## Fase 0.5: ingestão automática dos dados (M)

Hoje os CSVs são baixados à mão. A `origin/feat/webscraping` tem `scripts/download_public_datasets.py`, que baixa CEAP, cadastros, proposições e votações da Câmara e do Senado. A branch está muito atrás da `main` e não deve ser mergeada; traz-se só o script.

1. Trazer o script com `git show` e escrever os testes antes (rede mockada). Download parcial vira erro explícito.
2. Corrigir: verificação SSL ligada (o script a desliga, e as URLs funcionam com ela ligada), escrita em arquivo temporário seguida de renomeação, conferência contra `Content-Length`.
3. Manifesto declarativo versionado (fonte, ano, URL, destino, checksum), em vez de URLs fixas no código.
4. Cliente do TSE pela API CKAN (`dadosabertos.tse.jus.br/api/3/action/package_show?id=...`), que lista as URLs reais dos recursos. `resultados-2022` traz a totalização presidencial do 1º e do 2º turno em arquivos separados; candidatos, bens e prestação de contas respondem em `cdn.tse.jus.br`. O nome do recurso de redes sociais deve vir do CKAN, não de padrão adivinhado.
5. Fechar buracos: `senado/materias/materias.csv` (o ETL espera), proposições e votações além de 2024.
6. Encadear `download → build_parquet → dim_politicos` num comando, agendado na VM com lock, e gravar a data de cada carga para o juiz poder citá-la.
7. Cuidados: os arquivos do TSE são grandes (os 5 principais de 2022 somam cerca de 1,3 GB); conferir o disco da VM antes.

**Status (2026-10-10):** passos 1 a 6 entregues no código (PRs #53 e `feat/fase0-5-manifesto-e-agendamento`). Detalhes de uso e instalação em `docs/ingestion.md`. Pendente fora do código: instalar o timer na VM (`deploy/ingestion/`), o que depende de conferir disco e memória de lá. O passo 5 trouxe `senado/materias` pelo serviço `/dadosabertos/processo` (o `materia/pesquisa/lista` está descontinuado) e os anos 2022 a 2026 de Câmara e Senado. As votações da Câmara são baixadas, mas ainda não convertidas em parquet (Fase 2).

Fora do escopo: `scrape_dados_abertos_tse` (raspagem de HTML, lê só 10 itens e não baixa) e `url_scraper.py` (artigos de notícia).

## Fase 1: tools do TSE (G)

1. Descoberta: abrir os parquets na VM e documentar o esquema em `docs/data_schemas.md` (turnos, cargos, anos, UFs). Confirmar se o 2º turno foi ingerido.
2. Resultado: `get_election_result(cargo, ano, uf, turno)`, `get_candidate_votes(sq_candidato, ano, turno)`, `check_candidate_status` e `check_disqualification_motive`.
3. Perfil e patrimônio: `check_candidate_profile`, `get_candidate_assets`, `check_cash_and_special_assets`, `verify_official_social_media`.
4. Finanças de campanha: totais de receitas e despesas por candidato.
5. Guarda de especificidade: "primeiro turno" ou "a última eleição" sem ano vira INCONCLUSIVO (regra 3).
6. Golden v2: ao menos 10 claims de TSE nos três vereditos, incluindo 2º turno e candidato ambíguo.
7. Opcional: ampliar para 2018, 2020 e 2024 conforme o volume de dados.

## Fase 2: voto individual (M)

`get_member_vote(id_votacao, parlamentar)` e placar por partido, reaproveitando `/votacoes/{id}/votos`. Resolução do parlamentar antes (regra 2) e testes de timeout com mock.

## Fase 3: expor o que já existe (P)

Decidir se tramitação, vetos e presença entram no catálogo do roteador. Se entrarem, testar o roteamento e o limite de tools suportado pelo modelo local.

## Fase 4: cobertura e atualização (M)

- Rotina de atualização dos parquets (parte já entregue pela Fase 0.5).
- CEAP anterior a 2024 e parquets de matérias do Senado.
- Base normativa com campos de vigência e data de revisão, e mais tópicos além dos 12 atuais.

## Fase 5: avaliação que mede de verdade (M)

- Conjunto de claims escrito por quem não viu as tools, nunca usado para desenvolver.
- Métricas por veredito e taxa de INCONCLUSIVO indevido.
- Teste de neutralidade com pares de claims espelhadas (regra 6).
- Rodar como experimento no Langfuse.

## Ordem

Fase 0, Fase 0.5, Fase 1 (descoberta primeiro), Fases 2 e 3 em paralelo, Fases 4 e 5 acompanhando desde a Fase 1.
