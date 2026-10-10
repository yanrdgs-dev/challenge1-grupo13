# Ingestão das bases públicas

`download -> build_parquet -> dim_politicos`, incremental e agendável. Código em `src/etl/`
(`pipeline.py`, `download_datasets.py`, `tse_ckan.py`, `freshness.py`, `ingestion_state.py`), fontes
declaradas em `src/etl/datasets_manifest.json`.

## Como funciona

1. **Novidades.** Para cada fonte do manifesto o pipeline faz um `HEAD` e compara `ETag`/`Last-Modified`
   (ou o tamanho) com o registrado na última carga. Fontes dinâmicas e pequenas (`refresh: always`, ex.:
   matérias e lista de senadores do Senado) são baixadas sempre, mas só contam como novidade se o `sha256`
   mudou. Portal fora do ar não derruba a verificação: após 2 falhas seguidas de um host, os demais `HEAD`
   dele são pulados e a cópia local é mantida.
2. **Download.** Só do que mudou, com SSL ligado, escrita em `.part` + renomeação, conferência de
   `Content-Length`/`sha256` e 3 tentativas com espera para erros transitórios. Falha em qualquer fonte
   aborta antes do build (`--allow-partial` libera).
3. **Build em staging.** Os parquets são gerados em `processed.staging/` (com `dim_politicos.parquet` e
   `ingestion_info.json`) e só então trocados, entrada a entrada, em `processed/`. O router, que lê
   `processed/`, nunca vê dados pela metade, e uma falha deixa os parquets atuais intactos.
4. **Sem novidade, sem build.** O build só roda se houve novidade, se uma carga anterior ficou pendente
   (`pending_build` no estado), se ainda não há parquets publicados ou com `--force-build`.
5. **Lock.** `.ingestion.lock` impede duas execuções ao mesmo tempo; a segunda sai com código 0.

## Arquivos de estado

| Arquivo | Onde | Para quê |
|---|---|---|
| `.ingestion_state.json` | `datasets/` | impressão digital, `sha256` e data de cada fonte; carga pendente; última execução |
| `.ingestion.lock` | `datasets/` | lock da execução em andamento |
| `ingestion_info.json` | `processed/` | de onde veio cada dado e `dados_atualizados_em`, para o juiz citar a data da base |

## Uso manual

```bash
uv run python scripts/run_ingestion_pipeline.py --check          # só informa se há novidade
uv run python scripts/run_ingestion_pipeline.py                  # incremental completo
uv run python scripts/run_ingestion_pipeline.py --force          # rebaixa tudo
uv run python scripts/run_ingestion_pipeline.py --force-build    # reconstrói os parquets sem novidade
uv run python scripts/run_ingestion_pipeline.py --skip-download  # só o build
uv run python scripts/run_ingestion_pipeline.py --allow-partial  # builda mesmo com download falho
uv run python scripts/run_ingestion_pipeline.py --tse-anos 2022  # só esses anos do TSE
```

Códigos de saída: `0` sucesso ou nada a fazer (inclui "outra execução em andamento"); `1` algum download ou
o build falhou (os parquets publicados continuam os de antes).

## Agendamento na VM

O script `deploy/ingestion/run-ingestion.sh` roda o pipeline dentro da imagem do judge (`src/` e dependências
de produção), com `/srv/factcheck/data` montado em `/app/data` e limite de memória (`INGESTION_MEMORY`,
padrão `4g`). Um timer do systemd o executa a cada hora.

**Antes de instalar, confira a VM** (a primeira carga baixa ~19 GB e o build usa vários GB de memória):

```bash
ssh polis 'df -h /srv; free -h'
```

Precisa de ~25 GB livres em `/srv` (CSVs, parquets e o staging) e de memória para o limite escolhido. Se a VM
tiver pouca RAM, reduza `INGESTION_MEMORY` e adicione swap, ou rode a carga inicial em outra máquina.

Instalação (como `deploy`, com `sudo` para o systemd):

```bash
scp deploy/ingestion/run-ingestion.sh polis:/srv/factcheck/run-ingestion.sh
scp deploy/ingestion/factcheck-ingestion.service deploy/ingestion/factcheck-ingestion.timer polis:/tmp/
ssh polis 'chmod +x /srv/factcheck/run-ingestion.sh \
  && sudo mv /tmp/factcheck-ingestion.service /tmp/factcheck-ingestion.timer /etc/systemd/system/ \
  && sudo systemctl daemon-reload'
ssh polis '/srv/factcheck/run-ingestion.sh --check'            # confere a configuração sem baixar
ssh polis 'sudo systemctl start factcheck-ingestion.service'   # primeira carga (demorada)
ssh polis 'sudo systemctl enable --now factcheck-ingestion.timer'
```

Acompanhar:

```bash
ssh polis 'systemctl list-timers factcheck-ingestion.timer'
ssh polis 'journalctl -u factcheck-ingestion -n 100 --no-pager'
ssh polis 'cat /srv/factcheck/data/processed/ingestion_info.json | head -20'
```

Desfazer (os dados e os parquets publicados ficam como estão):

```bash
ssh polis 'sudo systemctl disable --now factcheck-ingestion.timer'
```

Os arquivos de `deploy/ingestion/` não são enviados pelo CD: ao alterá-los, copie de novo para a VM.

## Resultados de 2026

`resultados-2026` no CKAN do TSE só tinha relatórios em PDF logo após o 1º turno. Quando o TSE publicar a
votação por zona, o detalhe por seção e a totalização presidencial, o pipeline os baixa sozinho na rodada
seguinte (o log deixa de mostrar "ainda não publicado"), reconstrói `tse/votacao_munzona` e
`tse/detalhe_votacao_secao` e atualiza `dados_atualizados_em`. Até lá, claims sobre o resultado de 2026 são
`INCONCLUSIVO` (regra 3 da `AGENTS.md`).

## Limitações conhecidas

- `camara/votacoes` e `votacoesVotos` são baixados mas ainda não convertidos em parquet (Fase 2).
- A partição `ano=0` de `camara/proposicoes` vem do próprio CSV da Câmara (linhas sem ano de proposição).
- A troca de `processed/` é atômica por entrada de primeiro nível (`camara/`, `senado/`, `tse/`, ...), não
  entre elas: por frações de segundo uma consulta pode ver `tse/` novo e `camara/` antigo.
