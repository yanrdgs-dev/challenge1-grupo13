# Fluxo de mudança de prompt

Os prompts do router (`factcheck-router-system`) e do judge (`factcheck-judge`) ficam versionados no Langfuse. O texto local em `src/prompts/defaults.py` é a base do repositório e o plano B quando o Langfuse está fora do ar (ou o tracing está desligado).

## Como o serviço escolhe o prompt

- `get_prompt` busca a label `production` por padrão. `LANGFUSE_PROMPT_LABEL` troca a label (por exemplo, `staging`) no processo do serviço.
- Há cache de 60 s (`PROMPT_CACHE_TTL_SECONDS`). Depois de promover uma versão, ela chega aos serviços em até 1 minuto, sem novo deploy.
- Se o Langfuse não responder, o serviço usa o texto local e não tenta de novo por 30 s.
- Cada generation `llm.chat` do router e do judge fica ligada à versão do prompt usada. No Langfuse, abra o prompt e veja a aba de métricas por versão.

## Passo a passo

1. **Editar** o texto em `src/prompts/defaults.py`. Variáveis usam `{{nome}}`.
2. **Publicar como staging:**
   ```bash
   uv run python scripts/langfuse_push_prompts.py --dry-run   # lista os prompts
   uv run python scripts/langfuse_push_prompts.py
   ```
   Prompt inexistente é criado com a label `production` (migração inicial). Prompt diferente do de produção vira uma **nova versão com a label `staging`**, nunca direto em produção.
3. **Rodar o experiment contra o staging.** O experiment chama o router por HTTP, então a label vale no processo dos serviços:
   ```bash
   LANGFUSE_PROMPT_LABEL=staging uv run uvicorn src.services.router_service:app --port 8000
   LANGFUSE_PROMPT_LABEL=staging uv run uvicorn src.services.judge_service:app --port 8001
   uv run python scripts/run_golden_experiment.py --run-name prompt-<descricao>
   ```
4. **Comparar com o baseline** (`evaluation/baseline_v2.json`) e com o gate de `evaluation/thresholds.json`. Os scores que protegem as regras da constituição (`no_wrong_definitive`, `has_traceable_evidence`, `inconclusive_without_tool`) precisam continuar em 100%.
5. **Promover:** na interface do Langfuse, mova a label `production` para a versão aprovada. Para reverter, mova a label de volta para a versão anterior.
6. **Sincronizar o repositório:** o texto de `defaults.py` deve ser igual ao da versão em `production`. Faça o commit da mudança (`feat(prompts): ...`) junto com o resultado do experiment.

## Regras

- Mudança de prompt sem experiment não vai para `production` (regra 5).
- Reprovou no gate: a versão fica em `staging` ou é descartada, e a label `production` não muda.
- Um prompt `production` diferente do `defaults.py` quebra a reprodutibilidade do fallback. Mantenha os dois alinhados.
