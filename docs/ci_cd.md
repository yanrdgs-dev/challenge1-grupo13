# CI/CD (Fase 5)

Produção: **uma VM do Azure** com Docker Compose, com os parquets no disco dela. O modelo (Ollama) roda na máquina de desenvolvimento, exposto por túnel, e por isso o eval **não** é automático.

| Etapa | Arquivo | Quando roda | O que faz |
|---|---|---|---|
| CI (5.1) | `.github/workflows/ci.yml` | Todo PR e push na `main` | `uv sync --frozen` → `pytest` (tracing desligado, sem rede) → build das imagens router e judge → push para o GHCR com a tag do commit |
| Eval (5.2) | `scripts/run_eval.py` | **Manual**, com o Ollama ligado | Sobe judge e router, roda o golden experiment, aplica o gate e derruba tudo |
| CD (5.3) | `.github/workflows/cd.yml` | Depois do CI verde na `main`, ou manual | SSH na VM → `docker compose pull/up` com a imagem do commit → health check → rollback se falhar |

```
PR   ──► CI: pytest ──► build (tag = sha) ──► push GHCR
main ──► CI verde ──► CD: ssh na VM ──► compose up (IMAGE_TAG = sha) ──► /health ──► ok | rollback
(manual, antes de promover prompt/mudança de comportamento) ──► scripts/run_eval.py
```

## Eval manual

```bash
uv run python scripts/run_eval.py                                  # run com nome automático
uv run python scripts/run_eval.py --run-name prompt-novo --prompt-label staging
```

- Confere antes que o Ollama responde e que as portas 18000/18001 estão livres (medir o serviço de outra pessoa invalidaria o resultado). Falha rápido, em vez de gastar 25 minutos em 503.
- Usa `LLM_TIMEOUT=120` nos serviços, salvo se você definir outro valor no ambiente.
- Opções que o script não conhece (`--run-name`, `--local`, `--threshold`...) vão para `scripts/run_golden_experiment.py`.
- Código de saída: 0 = gate aprovado, 1 = reprovado, 2 = erro de infraestrutura. Os logs dos serviços ficam numa pasta temporária (o caminho é impresso ao final).
- **Quando rodar:** antes de promover um prompt para `production` (`docs/prompt_workflow.md`) e antes de mergear mudança em router, judge, resolvers ou tools. O resultado vai para o Langfuse (dataset run) e serve de evidência no PR.

## Configuração única

### GitHub (quem administra o repositório)

1. **Environment `production`** (*Settings → Environments*), de preferência com revisor obrigatório: o deploy espera aprovação.
2. **Secret** `AZURE_VM_SSH_KEY`: chave privada **só de deploy** (par criado para isso), sem acesso além do necessário.
3. **Variables:** `AZURE_VM_HOST`, `AZURE_VM_USER` (padrão `deploy`) e `AZURE_VM_KNOWN_HOSTS`. Esta última é a saída de `ssh-keyscan <host>` **conferida contra a impressão digital que o portal do Azure mostra**; o workflow não aceita host desconhecido.
4. **Proteção da `main`:** exigir os checks `test` e `build` do CI antes do merge.
5. **GHCR:** no primeiro push, conferir em *Packages* a visibilidade das imagens `factcheck-router` e `factcheck-judge`.

### VM do Azure (`polis-vm`)

Criada em 09/10/2026: grupo `polis-rg`, `northcentralus`, `Standard_B2as_v2` (2 vCPU, 8 GB), Ubuntu 24.04, disco de 64 GB, IP público estático, usuário `deploy`, login só por chave. O `Standard_B2ms` não existe nessa região para a assinatura de estudante, e a política da assinatura só permite `brazilsouth`, `southafricanorth`, `northcentralus`, `spaincentral` e `chilecentral`. Custo de tabela: cerca de US$ 0,075 por hora ligada; `az vm deallocate -g polis-rg -n polis-vm` para a cobrança de computação quando não estiver em uso.

Já preparado na VM:

- Docker (repositório oficial) e Compose; `deploy` no grupo `docker`.
- Rede Docker `factcheck` com sub-rede fixa: `docker network create --subnet 172.28.0.0/24 --gateway 172.28.0.1 factcheck`. O compose de produção entra nela como rede externa.
- `/srv/factcheck/` e `/srv/factcheck/data/processed/` (donos: `deploy`).
- `sshd` com `GatewayPorts clientspecified` (`/etc/ssh/sshd_config.d/61-factcheck-gateway.conf`), necessário para o túnel escutar no gateway da rede Docker.
- NSG `polis-vmNSG` com duas regras de entrada para a porta 22: `ssh-meu-ip` (só o IP da rede de desenvolvimento) e `ssh-cd` (origem `Internet`, aberta em 09/10/2026 para o GitHub Actions entrar). Não dá para limitar ao GitHub: são mais de 5.000 intervalos IPv4, acima do limite de 4.000 prefixos por regra do NSG, e a lista muda toda semana. A proteção é a chave (sem senha), o `sshd` endurecido e o `fail2ban` (4 falhas em 10 min = ban de 1 h). A chave do CD é própria (`factcheck_cd`, separada da de administração) e pode ser revogada removendo a linha `factcheck-cd-github-actions` do `authorized_keys`. Para fechar a porta: `az network nsg rule delete -g polis-rg --nsg-name polis-vmNSG -n ssh-cd`.

Falta fazer à mão: criar `/srv/factcheck/.env` (`chmod 600`) com `OLLAMA_BASE_URL=http://172.28.0.1:11434`, `LLM_TIMEOUT`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` e `LANGFUSE_TRACING_ENABLED` (modelo em `.env.example`), gerar os parquets em `/srv/factcheck/data/processed/` (plano em `docs/plan_webscraping.md`) e, se as imagens do GHCR forem privadas, `docker login ghcr.io` (token com `read:packages`). Abrir a porta do router no NSG só quando for publicar.

### Máquina com o Ollama

O Ollama roda na sua máquina e a VM o alcança por um túnel. Dois caminhos, conforme a rede:

**1. Túnel SSH reverso (`--ssh`), o que funciona em redes de campus e laboratório**

```bash
uv run python scripts/start_ollama_tunnel.py --ssh deploy@<ip-da-vm> --ssh-key ~/.ssh/factcheck_vm
```

A sua máquina abre a conexão até a VM (porta 22, que costuma estar liberada) e o Ollama passa a aparecer em `172.28.0.1:11434`, o gateway da rede Docker. Ele escuta **só** nesse endereço: os containers alcançam, o IP público da VM e a internet não. A barreira é a chave SSH; não usa Caddy nem `OLLAMA_API_KEY`.

- O endereço é fixo (`OLLAMA_BASE_URL=http://172.28.0.1:11434`): não muda a cada execução.
- Reconecta sozinho com backoff de 2 s até 60 s se a conexão cair, e zera o backoff depois de 30 s estável.
- O `known_hosts` precisa ter a VM (o script usa `StrictHostKeyChecking=yes` e `BatchMode`); confira a impressão digital com `az vm run-command invoke ... "ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub"`.
- Antes de anunciar, o autoteste roda `curl` **dentro da VM** contra o endereço do túnel.
- Testado em 09/10/2026: container na VM recebeu `HTTP 200` do Ollama da máquina local; a queda do `ssh` foi seguida de reconexão; `SIGTERM` limpou tudo.

**2. Cloudflare Tunnel + Caddy, para redes que liberam a porta 7844**

```bash
brew install caddy cloudflared        # sem admin: baixe os binários para ~/bin
export OLLAMA_API_KEY=$(openssl rand -hex 32)
uv run python scripts/start_ollama_tunnel.py
```

O `deploy/Caddyfile` só aceita `Authorization: Bearer <chave>` e só encaminha `/api/chat`, `/api/generate` e `/api/tags`; o script recusa chave com menos de 32 caracteres e prova o 401/200 antes de abrir o túnel. A URL do túnel rápido muda a cada execução (copie o `OLLAMA_BASE_URL` impresso para o `.env` da VM). **Na rede da UnB não funcionou:** o `cloudflared` não conecta porque a porta 7844 está bloqueada em UDP e TCP; use o `--ssh`. O `Caddyfile` foi validado com o Caddy real (`Valid configuration`) e o proxy respondeu como esperado em modo `--no-tunnel`.

Em qualquer caminho a máquina precisa ficar ligada e acordada (o script mantém o `caffeinate` no macOS). Se ela dormir, a VM recebe timeout.

## Frontend (Pólis)

```
navegador ──HTTPS :443──► Caddy ──► nginx (container frontend) ──► /api/*  ──► router-service ──► judge-service
 (HTTP :80 → redirect)                         └─► /, /assets/*  (build estático do Vite)
```

O **Caddy** é o único publicado na VM (portas 80 e 443). Frontend, router e judge ficam internos, só na rede do compose. O router passa a expor, além do `/check`, as rotas que o frontend usa (`src/services/frontend_api.py`), todas sobre o mesmo pipeline (guardrails → router → tool → judge → guardrails):

| Rota | O que faz |
|---|---|
| `GET /api/health` | Estático; não depende do Ollama. É o que o health check do CD consulta, por dentro do nginx |
| `GET /api/suggestions` | Sugestões da tela inicial |
| `POST /api/check` | `{query, session_id?}` → `{id, query, verdict, text, subdetails, sources, rule_matched}`. O `id` é o `trace_id` do Langfuse; o `text` é o texto do julgador, sem reescrita (regra 6) |
| `POST /api/check/stream` | Mesma resposta em SSE: eventos `step` (`tools`, `search`, `synthesis`, emitidos nas etapas reais do pipeline), `token` e `done`. Há `: keepalive` a cada 15 s, porque a checagem leva dezenas de segundos |
| `POST /api/feedback` | 👍/👎 vira o score categórico `feedback_usuario` no trace da resposta. Mensagens antigas do navegador (ids que não são trace ids) são aceitas e ignoradas |

**Comportamentos a conhecer**
- Os `token` do stream são o texto do veredito enviado em pedaços **depois** de o judge terminar: o judge não gera em streaming. O que é real é o progresso (`step`).
- Se o pipeline falhar no meio do stream (por exemplo, Ollama fora do ar), o stream termina com um `done` `INCONCLUSIVO`, `rule_matched: servico_indisponivel` e um texto de indisponibilidade, sem o erro técnico. Já `POST /api/check` devolve 503.
- O nginx limita as rotas de checagem a **20 requisições por minuto por IP** (rajada de 5) e devolve 429 acima disso: cada checagem ocupa o Ollama local por ~40 s. Atrás de um NAT compartilhado (rede de campus), vários usuários dividem esse limite. O frontend mostra a mensagem genérica "não foi possível conectar" em um 429.
- O frontend envia o `session_id` da conversa (`session-<timestamp>`, sem dado pessoal), que o Langfuse usa para agrupar as mensagens de um mesmo chat.
- **HTTPS (`polis.software`):** o Caddy (`deploy/Caddyfile.site`, enviado pelo CD para `/srv/factcheck/Caddyfile.site`) emite e renova sozinho o certificado Let's Encrypt, redireciona HTTP→HTTPS e o `www` para o domínio raiz. Os certificados ficam no volume `caddy_data`. O nginx confia no `X-Forwarded-For` só da rede do compose (`172.28.0.0/24`), para o limite de 429 continuar por cliente. O health check do CD segue em `http://localhost/api/health`, por um bloco `http://localhost` do Caddyfile, sem certificado.
- **Pré-requisitos do certificado:** registro `A` de `polis.software` e de `www` para o IP estático da VM (name.com) e NSG com 80 e 443 abertas (a 80 é necessária para o desafio do Let's Encrypt). Sem o DNS apontando, o Caddy sobe e fica tentando; o site em HTTPS só funciona depois que o DNS propagar.

**Para o site ficar acessível, falta abrir a porta 80 no NSG** (hoje só a 22 está aberta):
```
az network nsg rule create -g polis-rg --nsg-name polis-vmNSG -n http-publico --priority 1020 --direction Inbound --access Allow --protocol Tcp --source-address-prefixes Internet --destination-port-ranges 80
```
Para fechar: `az network nsg rule delete -g polis-rg --nsg-name polis-vmNSG -n http-publico`. E o Ollama precisa estar alcançável (túnel SSH ligado) para as checagens funcionarem; sem ele o site abre, mas toda checagem responde "indisponível".

**Validado na VM (09/10/2026, numa stack de teste isolada, antes do deploy):** `docker build` do frontend (inclui `tsc -b`) e do router; `nginx -t`; a casca da SPA sem cache, o asset com hash `immutable` e os cabeçalhos de segurança; `/api/*` pelo nginx; uma checagem real em streaming com o Ollama da máquina de desenvolvimento (`step=tools` em 0,0 s, ou seja, sem buffer; `done` aos 36 s com `VERDADEIRO` e fonte); o caminho de falha (503 e `done` de indisponibilidade); o feedback (`registrado: true` com trace id real); e o limite (6 passam, 19 recebem 429). **Não foi testado:** a interface num navegador (não há Node nem navegador automatizado aqui), então o comportamento visual, o histórico em `localStorage` e os botões de feedback não foram exercitados.

## Como o deploy se protege

- Só roda depois do CI verde na `main` (ou manualmente, com um SHA já publicado). O SHA é validado como 40 caracteres hexadecimais antes de ir para o comando remoto.
- A tag é imutável (o commit), nunca `latest`; `IMAGE_TAG` e `GHCR_OWNER` são obrigatórios no compose.
- A chave do host fica fixada; a chave privada vive só durante o job e é apagada no final.
- Se o `/health` não responder em ~2 minutos, o script volta para a tag anterior (`/srv/factcheck/.current_tag`) e o job falha.
- Deploys são serializados e nunca cancelados no meio.

## Limitações conhecidas

- Nenhum dos workflows rodou no GitHub ainda; a estrutura é validada por `tests/test_ci_workflow.py` e `tests/test_cd.py`, e os scripts de shell tiveram a sintaxe conferida com `bash -n`. O primeiro deploy real vai exigir ajustes.
- O rollback só desfaz a imagem; mudança incompatível nos parquets não é revertida.
- O `cd.yml` ainda não rodou: faltam o environment `production`, o secret `AZURE_VM_SSH_KEY` e as variables `AZURE_VM_HOST` e `AZURE_VM_KNOWN_HOSTS`, e a porta 22 aberta à internet é superfície de ataque (varredura constante).
- O frontend tem imagem (`docker/Dockerfile.frontend`) e entra no compose de produção e no CI (build + `nginx -t`), e fica visível na internet pelo Caddy (portas 80 e 443 abertas no NSG).
- A VM é um ponto único de falha; vale um backup do `data/processed` (a ingestão regenera os parquets, mas o tempo ainda não foi medido).
- As actions estão fixadas por versão maior (`@v4`, `@v6`), não por SHA.
- O achado 3 do plano segue aberto: sem fallback, um timeout do Ollama vira 503.

## Provedores de LLM (cadeia com disjuntor e teto diário)

O `LLMClient` percorre uma cadeia ordenada, definida em `LLM_PROVIDERS` (padrão recomendado: `ollama,groq,deepseek`). A lógica é custo zero primeiro: o Ollama local, depois a Groq gratuita, e o DeepSeek pago só se os dois falharem. Sem `LLM_PROVIDERS`, valem `LLM_PROVIDER` e `FALLBACK_PROVIDER` como antes.

- **Disjuntor** (`src/core/provider_guard.py`): depois de `LLM_BREAKER_FAILURES` falhas seguidas (3), o provedor é pulado por `LLM_BREAKER_COOLDOWN` segundos (120), sem esperar o timeout a cada checagem. Passado o tempo, uma única requisição testa o provedor; se der certo, ele volta a ser o primeiro (é assim que o Mac reassume o Ollama). Se todos os disjuntores estiverem abertos, a cadeia tenta mesmo assim.
- **Teto diário:** por padrão só o DeepSeek, com 200 chamadas por dia UTC (`DEEPSEEK_DAILY_CAP`; `0` desliga). Tentativas que falham também contam. Acima do teto, nenhuma chamada paga é feita e o agente devolve a mensagem de indisponibilidade, nunca um palpite.
- **Erro de configuração** (chave ausente) passa ao próximo provedor e não abre o disjuntor.
- **Limitações:** o estado fica na memória de cada processo. O roteador e o juiz são serviços separados, então cada um tem o seu contador (o teto efetivo pode chegar ao dobro), e um reinício zera as contagens. O saldo real continua sendo o do painel do DeepSeek.
- **Modelos:** o roteador pede `qwen2.5:7b` e o juiz `qwen2.5:14b` ao Ollama. Groq, OpenAI e DeepSeek usam um modelo único por provedor, vindo do ambiente (`GROQ_MODEL`, `DEEPSEEK_MODEL`...). O padrão da Groq (`llama-3.1-8b-instant`) fica abaixo do 14b do juiz: configure um modelo maior e rode o golden dataset antes de confiar nos vereditos.
- **Privacidade:** com a Groq e o DeepSeek, o texto da alegação e a evidência saem da infraestrutura do projeto.

