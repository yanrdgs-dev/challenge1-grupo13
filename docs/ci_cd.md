# CI/CD (Fase 5)

Dois workflows em `.github/workflows/`:

| Workflow | Roda em | O que faz | Bloqueia merge? |
|---|---|---|---|
| `ci.yml` (5.1) | GitHub-hosted, em todo PR e push na `main` | `uv sync --frozen` → `pytest` com `LANGFUSE_TRACING_ENABLED=false` → build das imagens router e judge → push para o GHCR com a tag do commit | Sim, com o job `test` como check obrigatório |
| `eval.yml` (5.2) | Runner **self-hosted** na VM, PR do próprio repositório, push na `main` e execução manual | Sobe judge e router (portas 18001/18000), roda o golden experiment e aplica o gate de `evaluation/thresholds.json` | Sim, com o job `golden` como check obrigatório |
| CD (5.3) | — | `overlays/prod` + ArgoCD. **Não implementado.** | — |

```
PR   ──► ci.yml: pytest ──► build (tag = sha) ──► push GHCR
     └─► eval.yml (VM): golden experiment ──► gate (regra 5)
main ──► (5.3) overlays/prod ──► ArgoCD
```

## Por que o eval roda na VM

Os parquets de `data/processed/` não estão no Git (são gerados na VM) e o Ollama com os modelos Qwen também está lá. Um runner do GitHub não teria nem os dados nem o LLM. O workflow liga `FACTCHECK_DATA_DIR` a `data/processed` e falha logo se o diretório não existir, para não medir o dado errado.

**Segurança:** um self-hosted runner executa o código do PR na VM. Por isso o job `golden` só roda para PR do mesmo repositório (`head.repo.full_name == github.repository`) e nunca para fork. Mantenha também em *Settings → Actions → General* a exigência de aprovação para PRs de colaboradores externos.

## Configuração única (quem administra o repositório)

1. **Runner:** registrar o runner na VM com a label `factcheck-vm` (*Settings → Actions → Runners*). Rodar como usuário sem privilégios, nunca como root.
2. **Secrets** (*Settings → Secrets and variables → Actions*): `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`.
3. **Variables:**
   - `FACTCHECK_DATA_DIR`: caminho absoluto dos parquets na VM (obrigatória).
   - `OLLAMA_BASE_URL`: opcional, padrão `http://localhost:11434`.
   - `LANGFUSE_BASE_URL`: opcional, padrão `https://us.cloud.langfuse.com`.
4. **Proteção da `main`:** exigir os checks `test`, `build` e `golden` antes do merge.
5. **GHCR:** no primeiro push, conferir em *Packages* a visibilidade das imagens `factcheck-router` e `factcheck-judge`. Se o repositório for privado, o cluster precisa de um `imagePullSecret` com token de leitura.

## Rodar o eval manualmente

*Actions → Eval → Run workflow*. O campo `prompt_label` escolhe a label dos prompts no Langfuse (`staging` para testar uma versão nova antes de promover; ver `docs/prompt_workflow.md`). O log e os logs dos serviços ficam como artefato do run.

## Limitações conhecidas

- O eval usa o Ollama da VM sem fallback. Um timeout vira 503 e o gate reprova por infraestrutura, não por qualidade (achado 3 do plano). O workflow fixa `LLM_TIMEOUT=120`, mas o experiment ainda não distingue "erro" de "veredito errado".
- Os pods do router no Kubernetes ficam sem dados até haver um volume (PVC ou `hostPath` na VM) com os parquets: a imagem não os contém mais.
- As actions estão fixadas por versão maior (`@v4`, `@v6`), não por SHA.
- Nenhum dos dois workflows foi executado no GitHub ainda; só a estrutura é validada por `tests/test_ci_workflow.py` e `tests/test_eval_workflow.py`.
