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
| `.ingestion_state.json` | `datasets/` | impressão digital, `sha256` e data de cada fonte; carga pendente; histórico das últimas 50 execuções; memória dos avisos |
| `.ingestion.lock` | `datasets/` | lock da execução em andamento |
| `ingestion_info.json` | `processed/` | de onde veio cada dado e `dados_atualizados_em`, para o juiz citar a data da base |
| `ingestion_status.json` | `processed/` | resumo da última execução (lido por `/api/ingestion/status`), atualizado a cada rodada |

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

## Ver o estado da ingestão

Quatro jeitos, do mais simples ao mais automático:

```bash
# 1. No terminal (na VM ou local): última execução, novidades, falhas, histórico
ssh polis '/srv/factcheck/run-ingestion.sh --status'
ssh polis '/srv/factcheck/run-ingestion.sh --status --json'
ssh polis '/srv/factcheck/run-ingestion.sh --status --max-age-hours 6'   # código 2 se o último sucesso for mais velho

# 2. Página no site (atualiza sozinha a cada minuto): https://polis.software/status
#    Também há o link "Estado dos dados" no rodapé da barra lateral do verificador.

# 3. JSON do router (público, sem segredo): https://polis.software/api/ingestion/status
curl -s https://polis.software/api/ingestion/status | python3 -m json.tool

# 4. O arquivo que a ingestão publica junto dos parquets
cat /srv/factcheck/data/processed/ingestion_status.json
```

O que o estado mostra: quando foi a última execução e se terminou OK, se encontrou novidades e quantas por origem
(Câmara, Senado, TSE), se o build publicou, falhas (com a mensagem), quantas execuções seguidas falharam, quando foi o
último sucesso, a última carga com novidade, a data dos dados e as 10 últimas execuções. O endpoint acrescenta
`ultimo_sucesso_ha_horas` e `desatualizada` (padrão: sem sucesso há mais de 6 h; ajustável com
`INGESTION_STALE_HOURS` no router).

## Avisos de falha e de novidade

Dois mecanismos complementares, ambos opcionais e configurados só por variáveis de ambiente, no arquivo
`/srv/factcheck/ingestion.env` (modo 600, criado só na VM; **não** é o `.env` dos serviços):

```bash
ssh polis 'install -m 600 /dev/null /srv/factcheck/ingestion.env && nano /srv/factcheck/ingestion.env'
chmod 600 /srv/factcheck/ingestion.env
```

```
INGESTION_WEBHOOK_URL=https://discord.com/api/webhooks/...      # Discord, Slack, ntfy ou JSON genérico
INGESTION_HEARTBEAT_URL=https://hc-ping.com/<uuid>              # healthchecks.io (ou similar)
INGESTION_NOTIFY=changes                                        # failures | changes (padrão) | always | off
```

Sem aspas e sem espaços ao redor do `=`.

1. **Webhook** (aviso escrito). Formato escolhido pela URL: Discord (`discord.com/api/webhooks`), Slack
   (`hooks.slack.com`), ntfy (`ntfy.sh/<tópico>`, o mais simples: instala o app no celular e assina o tópico) ou
   JSON `{"title","text"}`. Avisa em: **falha** (com os erros), **recuperação** (primeira execução boa depois de
   falha) e **novidade** (fontes novas e se o build publicou). A mesma falha não é repetida a cada hora: só na
   primeira vez, quando muda, ou depois de 6 h. `INGESTION_NOTIFY=failures` silencia as novidades; `always`
   avisa toda execução; `off` desliga tudo.
2. **Heartbeat** (aviso de que a ingestão *parou*). A cada execução boa o pipeline pinga a URL (e `/fail` se
   falhou). No [healthchecks.io](https://healthchecks.io) (plano gratuito) crie um check com período de 1 h e
   tolerância de 2 h: se os pings pararem, ele avisa por e-mail/Telegram/Slack. É a única forma de saber que a
   ingestão deixou de rodar (VM fora, timer desligado, container morto por falta de memória), porque nesses
   casos nenhum código da própria ingestão chega a executar.

O `run-ingestion.sh` também avisa quando o container morre sem o pipeline conseguir se explicar (código 137 =
sem memória, 125 = erro do Docker). Consultas (`--status`, `--check`) nunca geram alerta.

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
ssh polis '/srv/factcheck/run-ingestion.sh --check'            # confere a configuração sem baixar (sem criar avisos)
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

## O que o timer NÃO cobre sozinho

- Quem ler `processed/` em memória precisa recarregar: o `PoliticianCache` (catálogo de parlamentares) faz isso sozinho quando o `dim_politicos.parquet` muda.
- O CD não envia `deploy/ingestion/`: ao mudar o script, o service ou o timer, copie de novo para a VM.

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
