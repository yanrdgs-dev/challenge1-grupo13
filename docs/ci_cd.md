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
- Sem o frontend: ele ainda não tem Dockerfile (Fase 7). Quando tiver, entra no `docker-compose.prod.yml` e no build do CI.
- A VM é um ponto único de falha; vale um backup do `data/processed` (a ingestão regenera os parquets, mas o tempo ainda não foi medido).
- As actions estão fixadas por versão maior (`@v4`, `@v6`), não por SHA.
- O achado 3 do plano segue aberto: sem fallback, um timeout do Ollama vira 503.
