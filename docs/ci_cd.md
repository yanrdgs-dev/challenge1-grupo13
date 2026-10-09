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

### VM do Azure

```bash
sudo mkdir -p /srv/factcheck/data/processed
sudo chown -R deploy:deploy /srv/factcheck
# Docker + plugin compose instalados; o usuário `deploy` no grupo docker.
# Se as imagens forem privadas: docker login ghcr.io -u <usuario> (token com read:packages), uma vez.
```

- `/srv/factcheck/.env` (só na VM, `chmod 600`): `OLLAMA_BASE_URL` (URL do túnel), `OLLAMA_API_KEY`, `LLM_TIMEOUT`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`, `LANGFUSE_TRACING_ENABLED`. Modelo em `.env.example`.
- `/srv/factcheck/data/processed/`: os parquets, gerados pelo pipeline de ingestão (`docs/plan_webscraping.md`) na própria VM. O router monta essa pasta somente leitura.
- Abrir só a porta do router (8000, ou 80/443 atrás de um proxy). O judge não é publicado.

### Máquina com o Ollama

```bash
brew install caddy cloudflared
export OLLAMA_API_KEY=$(openssl rand -hex 32)     # guarde: a VM precisa da mesma chave
uv run python scripts/start_ollama_tunnel.py
```

O script usa `deploy/Caddyfile`: o proxy só aceita `Authorization: Bearer <chave>` e só encaminha `/api/chat`, `/api/generate` e `/api/tags` (ninguém remoto baixa ou apaga modelos, nem com a chave). Antes de abrir o túnel ele prova que o proxy responde 401 sem a chave e 200 com ela. Recusa chave vazia ou com menos de 32 caracteres, porque chave vazia deixaria a porta aberta.

- O túnel rápido do Cloudflare **muda de URL a cada execução**. O script imprime o `OLLAMA_BASE_URL` novo; copie-o para `/srv/factcheck/.env` da VM e recrie os containers. URL fixa exige um túnel nomeado (domínio próprio).
- A máquina precisa ficar ligada e acordada; no macOS o script mantém o `caffeinate` enquanto roda. Se ela dormir, a VM recebe timeout.
- `--no-tunnel` sobe só o proxy, para testar localmente.
- O `Caddyfile` não foi validado com o Caddy real neste repositório (não estava instalado); o script roda `caddy validate` antes de subir, e o autoteste 401/200 é a prova de que o porteiro funciona.

## Como o deploy se protege

- Só roda depois do CI verde na `main` (ou manualmente, com um SHA já publicado). O SHA é validado como 40 caracteres hexadecimais antes de ir para o comando remoto.
- A tag é imutável (o commit), nunca `latest`; `IMAGE_TAG` e `GHCR_OWNER` são obrigatórios no compose.
- A chave do host fica fixada; a chave privada vive só durante o job e é apagada no final.
- Se o `/health` não responder em ~2 minutos, o script volta para a tag anterior (`/srv/factcheck/.current_tag`) e o job falha.
- Deploys são serializados e nunca cancelados no meio.

## Limitações conhecidas

- Nenhum dos workflows rodou no GitHub ainda; a estrutura é validada por `tests/test_ci_workflow.py` e `tests/test_cd.py`, e os scripts de shell tiveram a sintaxe conferida com `bash -n`. O primeiro deploy real vai exigir ajustes.
- O rollback só desfaz a imagem; mudança incompatível nos parquets não é revertida.
- Sem o frontend: ele ainda não tem Dockerfile (Fase 7). Quando tiver, entra no `docker-compose.prod.yml` e no build do CI.
- A VM é um ponto único de falha; vale um backup do `data/processed` (a ingestão regenera os parquets, mas o tempo ainda não foi medido).
- As actions estão fixadas por versão maior (`@v4`, `@v6`), não por SHA.
- O achado 3 do plano segue aberto: sem fallback, um timeout do Ollama vira 503.
