# Plano de Execução: Pipeline de LLMOps com Langfuse

Plano para adicionar observabilidade, gestão de prompts, avaliação contínua e CI/CD ao agente de fact-checking, com deploy em Docker + Kubernetes.

## Diagnóstico do estado atual

Quatro pontos do repositório mudam a ordem natural das fases:

1. **Existem dois fluxos de fact-checking separados.** O `src/api` (API Pólis com guardrails) é o que o frontend usa. O `router_service` → `judge_service` é o que vai para o Kubernetes, e ele não passa pelos guardrails.
2. **O router e o judge chamam o Ollama direto**, sem passar pelo `LLMClient` (`src/core/llm_client.py`).
3. **O guia de Kubernetes cita um `k8s/kustomization.yaml` que não existe** no repositório. As imagens usam tags fixas (`:v2`).
4. **5 testes já falham em `tests/test_build_parquet.py`.** Isso trava qualquer gate de CI.

---

## Fase 0: Preparação (bloqueia as outras)

**Objetivo:** ter um único fluxo, todas as chamadas de LLM num só lugar e a suíte de testes passando.

| # | Tarefa | Teste antes (TDD) |
|---|---|---|
| 0.1 ✅ | Corrigir o `build_parquet.py` (`total_cols_before`, `selected_cols`, parâmetro `selected_columns`) | Os 5 testes que já existem |
| 0.2 ✅ | Adicionar ao `LLMClient` um método `chat(messages, tools)` que devolve as tool calls e o uso de tokens | Mock do `httpx`: caminho feliz, timeout, fallback para Groq |
| 0.3 ✅ | Fazer o router e o judge usarem o `LLMClient` | Testes dos serviços com o `LLMClient` mockado |
| 0.4 ✅ | Colocar os guardrails (`FactCheckingGuardrails`) no `/check` do router | Claim subespecificada → INCONCLUSIVO sem chamar tool |
| 0.5 ✅ | Ligar ao `execute_tool` do router as 4 tools de dados do catálogo (que caíam num ramo "simulado"), com resolução de entidade antes (regra 2) | Despacho de cada tool, nome→ID, entidade não resolvida/ambígua sem chamar a tool de dados |

**Pronto quando:** `uv run pytest` passa 100% e existe um único caminho claim → guardrails → router → tool → judge → guardrails.

**Commits:** `fix(etl): ...`, `test(core): ...`, `refactor(services): usa LLMClient`, `feat(services): integra guardrails ao router`.

---

## Fase 1: Langfuse (Cloud)

> **Decisão:** Langfuse Cloud em todos os ambientes. A tarefa 1.2 (Helm self-hosted) foi descartada, e o `LANGFUSE_BASE_URL` aponta para `https://cloud.langfuse.com`.

| # | Tarefa |
|---|---|
| 1.1 ✅ | Reorganizar `k8s/` em `base/` + `overlays/dev`, com a lista de imagens no Kustomize (o fim das tags `:v2`) |
| 1.2 ❌ | ~~Instalar o Langfuse com o Helm chart oficial (`langfuse/langfuse`) no namespace `langfuse`, com os valores em `deploy/langfuse/values.dev.yaml`~~ (descartada: Cloud) |
| 1.3 ✅ | Criar o `Secret` `factcheck-langfuse` (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`) e colocar `LANGFUSE_BASE_URL` no ConfigMap |
| 1.4 ✅ | Atualizar o `docs/kubernetes_setup_guide.md` |

**Pronto quando:** o projeto existe no Langfuse Cloud, o Secret `factcheck-langfuse` está criado no cluster e um trace de teste aparece na interface (validado na Fase 2).

---

## Fase 2: Instrumentação (tracing)

| # | Tarefa | Teste antes |
|---|---|---|
| 2.1 ✅ | Rodar `uv add langfuse` e criar o módulo `src/observability/tracing.py`: um wrapper que vira no-op quando o tracing está desligado e que nunca derruba a request se o Langfuse falhar | Desligado ⇒ zero chamadas de rede. Erro no Langfuse ⇒ a resposta continua normal |
| 2.2 ✅ | Instrumentar o `LLMClient`: cada chamada vira uma generation com modelo, provider, tokens e latência | O uso de tokens é extraído da resposta do Ollama (`prompt_eval_count`, `eval_count`) e do Groq |
| 2.3 ✅ | Criar spans para guardrails de entrada e saída, `resolve_*`, `execute_tool` e judge | Estrutura do trace verificada com mock |
| 2.4 ✅ | Propagar o trace do router para o judge (header `traceparent`) | O judge recebe o header e se pendura no mesmo trace |
| 2.5 ✅ | Gravar no trace `veredito`, `tool_usada` e `release = GIT_SHA`, e devolver o `trace_id` no `CheckResponse` | Contrato da resposta |
| 2.7 ✅ | Registrar o veredito final como **score categórico** `veredito` no trace (`VERDADEIRO` / `FALSO` / `INCONCLUSIVO`) | O score reflete o veredito depois do output rail, inclusive em claims bloqueadas |
| 2.8 ✅ | Aceitar `session_id` e `user_id` **opcionais** no `/check` e propagá-los a todos os spans (`propagate_attributes`) | Sem ids (deslogado) o fluxo funciona igual. Só `session_id` também vale. Ids em branco ou com mais de 200 caracteres são ignorados |
| 2.6 ✅ | Chamar `flush()` no encerramento do FastAPI e configurar `preStop` no Deployment | — |

**Score `veredito`:** score categórico anexado ao trace no fim do `/check`. No Langfuse ele permite filtrar traces por veredito e montar o gráfico de distribuição de vereditos (6.3) sem depender de metadata. O feedback do usuário (6.1) será outro score, no mesmo trace, com o `trace_id` devolvido na resposta. A *score config* `veredito` (categórica, com as três categorias) já foi criada no projeto do Langfuse. Para o código também ser barrado em valores fora do conjunto, passar o `config_id` no score (candidato à 6.4).

**`session_id` e `user_id`:** campos opcionais do corpo do `/check`. O frontend gera um `session_id` por conversa (também para quem não está logado) e envia o `user_id` apenas quando houver login. Use ids opacos: nunca e-mail, CPF ou nome. Com `session_id`, o Langfuse agrupa as mensagens de um mesmo chat.

Estrutura esperada de um trace:

```
trace: check_claim  (session_id, user_id, release)
├── span: guardrails.input
├── generation: router            (modelo, tokens, latência, versão do prompt)
├── span: resolve_politician / resolve_proposition
├── span: tool.<nome>             (args + evidência)
├── generation: judge             (no judge-service, via traceparent)
└── span: guardrails.output
```

**Pronto quando:** um `/check` no cluster gera **um único trace** com o router e o judge aninhados, e os testes passam com o Langfuse desligado.

**Validação real (08/10/2026):** serviços rodando localmente (Ollama `qwen2.5` + Langfuse Cloud US, `GIT_SHA=afede10`). Confirmado no Langfuse:
- Um `/check` completo gera **um único trace** com o `judge.evaluate` aninhado em `judge.call` e as duas generations (`qwen2.5:7b` no router, `qwen2.5:14b` no judge) com tokens de entrada e saída.
- `release`, `session_id`, `user_id`, metadata (`veredito`, `tool_usada`) e o score categórico `veredito` aparecem como esperado.
- Claim bloqueada na entrada: o trace só tem `check_claim` e `guardrails.input`, sem LLM, tool nem judge.
- Request anônima (sem `session_id` nem `user_id`) funciona e gera trace normal.
- O encerramento por `SIGTERM` executa o shutdown do FastAPI nos dois serviços.

**Achados da validação (tratar na Fase 3):**
1. ✅ **Resolvido:** a fonte primária agora é derivada da tool que executou (`src/services/sources.py`). Nomes de tool citados como "fonte" são descartados e o texto sempre cita a fonte. Evidência com erro, entidade não resolvida ou "não encontrado" nunca sustenta veredito. *Problema original:* na claim do CEAP 2023 a evidência confirmava Pompeo de Mattos, mas o judge citou o nome da tool (`get_top_ceap_spender`) como fonte e o texto não continha uma palavra-chave oficial, então o rail trocou para `INCONCLUSIVO`. O judge deve citar o órgão (por exemplo, "Câmara dos Deputados"), ou a fonte deve ser derivada da tool. Isso derruba o baseline do golden experiment.
2. ✅ **Resolvido pela 7.1:** as tools `check_institutional_rule` e `check_data_source_coverage` entraram no catálogo. Teste manual com o `qwen2.5:7b` em 8 claims normativas do golden dataset (3, 6, 10, 12, 16, 19, 21, 22, 24): todas foram para a tool e os argumentos corretos. A claim 19 falhou na primeira execução (nenhuma tool) e acertou na seguinte, ou seja, o roteamento **varia entre execuções**. *Problema original:* a pergunta sobre a sabatina do STF foi roteada para `resolve_proposition`.
3. **Sem fallback configurado, o timeout do Ollama vira 503.** Sem `GROQ_API_KEY`, uma pausa do Ollama (o Mac parado, o modelo carregando) derruba o `/check`. Decidir se o fallback fica ligado.
4. **Exportação do Langfuse é best effort.** Com a rede instável, parte dos spans foi perdida (um trace veio sem o `guardrails.input`). A request nunca falhou por causa do tracing. Em avaliações, conferir a contagem de observações.
5. **Roteamento não determinístico.** O Ollama usa temperatura padrão (0,8). Para o experiment da Fase 3 ser comparável entre execuções, fixar `temperature: 0` no router e no judge (via `options` do Ollama) e medir a variação do baseline.
6. **A API de traces legada devolve 410** em organizações novas. Para consultar traces por código, usar `observations.get_many` e `scores_v3` (já usados nos scripts de validação).

---

## Fase 3: Golden dataset e experiments (o portão de aceite da regra 5)

| # | Tarefa | Teste antes |
|---|---|---|
| 3.1 ✅ | Criar `src/evaluation/scorers.py` com scorers determinísticos, todos funções puras: `verdict_match`, `has_traceable_evidence`, `inconclusive_without_tool` e `tool_category_match` | Unitários para cada scorer |
| 3.2 ✅ | Criar `scripts/langfuse_sync_dataset.py`: envia o `golden_dataset_v1.json` de forma idempotente, usando o `id` | Mock do client |
| 3.3 ✅ | Criar `scripts/run_golden_experiment.py`: roda as 30 claims, registra os scores, imprime a matriz de confusão e sai com erro se ficar abaixo do limiar | Mock do client |
| 3.4 ✅ | Fazer um run de baseline e definir o limiar do gate | — |

**Scorers implementados (`src/evaluation/scorers.py`):** `verdict_match`, `no_wrong_definitive`, `has_traceable_evidence`, `inconclusive_without_tool` e `tool_category_match`. O `no_wrong_definitive` foi acrescentado depois do baseline: ele reprova qualquer veredito definitivo (`VERDADEIRO`/`FALSO`) diferente do esperado e aceita errar para `INCONCLUSIVO`. O dataset só tem `category`, então o `tool_category_match` checa se a tool pertence ao conjunto permitido da categoria (as tools de regra institucional valem nas duas).

**Como rodar:**
```bash
uv run python scripts/langfuse_sync_dataset.py                  # envia o dataset (idempotente)
uv run python scripts/run_golden_experiment.py --run-name <nome> # roda as 30 claims e aplica o gate
```
Saída: matriz de confusão, score por métrica, claims erradas (com `trace_id`) e código de saída 0 (aprovado), 1 (reprovado) ou 2 (erro). Os limiares ficam em `evaluation/thresholds.json`. Com `temperature: 0` no router e no judge.

**Baseline (08/10/2026, commit `185fadf`, `qwen2.5:7b` no router e `qwen2.5:14b` no judge):**

| Score | Resultado | Limiar do gate |
|---|---|---|
| `verdict_match` | 83,3% (25/30) | 80% |
| `tool_category_match` | 100% (n=24) | 95% |
| `has_traceable_evidence` | 100% | 100% (regra 1) |
| `inconclusive_without_tool` | 100% (n=6) | 100% (regra 3) |
| `no_wrong_definitive` | 100% (0 trocas entre `VERDADEIRO` e `FALSO`) | 100% |

Matriz de confusão (linhas = esperado): `VERDADEIRO` 9 certos e 3 `INCONCLUSIVO`; `FALSO` 10 certos e 2 `INCONCLUSIVO`; `INCONCLUSIVO` 6 de 6. Todos os 5 erros são para o lado seguro. O baseline completo está em `evaluation/baseline_v1.json`.

**Por que o sistema errou (claims 4, 5, 11, 15, 17):**
1. **Roteamento de uma etapa só (claims 4, 5, 15).** O router executa uma tool por claim. Para votações o LLM precisa de `resolve_proposition` e depois `get_proposition_vote_result`; sem a segunda etapa, ele **inventa** o `id_proposicao` (12345, 5678) ou para na resolução. A regra 2 funcionou (IDs inventados dão evidência vazia, não veredito), mas o acerto cai. Correção: roteamento em duas etapas, em que o resultado do resolver alimenta a tool de dados.
2. **Escolha de tool do modelo de 7B (claims 11 e 17).** A claim 11 ("pode pedir reembolso de alimentação") foi para `check_parliamentary_expenses` sem o `ano` obrigatório, e o certo seria `list_expense_categories`. A claim 17 (CEAPS e passagens) foi para `check_institutional_rule` com um tópico da Câmara. Correção: melhorar o prompt/descrições das tools (Fase 4, com experiment para medir) e validar parâmetros obrigatórios antes de executar.

**Pendências derivadas (candidatas a nova tarefa):**
| # | Tarefa | Teste antes |
|---|---|---|
| 3.5 ✅ | Roteamento em duas etapas para votações e gastos por parlamentar (resolve, depois dado), sem aceitar IDs vindos do LLM | O ID da tool de dados vem sempre do resolver. Claim 4/5/15 chegam à tool de votação |
| 3.6 ✅ | Validar parâmetros obrigatórios da tool antes de executar e devolver erro claro | `ano` ausente não vira `KeyError` silencioso |
| 3.7 ✅ | Rodar o experiment após cada mudança e subir o limiar de `verdict_match` | O gate sobe junto com a acurácia |

**Resultado após as tarefas 3.5 e 3.6 (v2, commit `545a69c`):**

| Score | v1 (baseline) | v2 | Limiar do gate |
|---|---|---|---|
| `verdict_match` | 83,3% (25/30) | **86,7% (26/30)** | 83,33% (25/30) |
| `no_wrong_definitive` | 100% | 100% | 100% |
| `has_traceable_evidence` | 100% | 100% | 100% |
| `inconclusive_without_tool` | 100% | 100% | 100% |
| `tool_category_match` | 100% | 100% | 95% |

Só a claim 4 passou a acertar (resolver o PL 2630 e depois consultar a votação encontra o "Requerimento de Urgência aprovado"). O limiar de `verdict_match` subiu de 80% para 83,33% (25/30), deixando a margem de uma claim para a variação do modelo. Subir para 86,7% quando duas execuções seguidas repetirem o resultado. O baseline está em `evaluation/baseline_v2.json`.

**As 4 claims que ainda erram e por quê (todas para o lado seguro):**
| Claim | Causa | Onde se resolve |
|---|---|---|
| 5 (Reforma Tributária) | O resolver devolve candidatos ambíguos, incluindo requerimentos `REQ`, para "PEC da Reforma Tributária" | Nova tarefa 3.8 |
| 15 (Marco Temporal) | O encadeamento funcionou, mas a tool devolve só a lista de votações. O placar ("unânime") exige `get_proposition_vote_breakdown`, que não está no catálogo | Nova tarefa 3.9 |
| 11 (reembolso de alimentação) | O LLM escolheu `check_parliamentary_expenses` em vez de `list_expense_categories` | Fase 4 (prompts) |
| 17 (CEAPS e passagens) | O LLM usou `check_institutional_rule` com um tópico da Câmara | Fase 4 (prompts) |

| # | Nova tarefa | Teste antes |
|---|---|---|
| 3.8 | Melhorar o `resolve_proposition` para termos populares: filtrar pela sigla quando o termo cita PEC/PL/MPV e preferir a proposição principal a requerimentos | "PEC da Reforma Tributária" resolve para uma `PEC`, e não para `REQ` |
| 3.9 | Expor o placar da votação (`get_proposition_vote_breakdown`) na etapa 2 do encadeamento | A evidência traz sim/não/abstenção por votação |

**Observações:** (a) um item do experimento não foi vinculado à execução no Langfuse por timeout de SSL (a rede estava instável); a contagem de itens deve ser conferida na interface. (b) O neutralidade por LLM-as-judge continua para a Fase 6.2.

Mapeamento dos scores para as regras da constituição (`AGENTS.md`):

| Score | Tipo | Regra |
|---|---|---|
| `verdict_match` | determinístico | 5 |
| `has_traceable_evidence` (veredito ≠ INCONCLUSIVO ⇒ tool + fonte presentes) | determinístico | 1 |
| `inconclusive_without_tool` (subespecificada ⇒ INCONCLUSIVO sem chamar tool) | determinístico | 3 |
| `tool_category_match` (tool chamada bate com a `category`) | determinístico | 4 |
| `neutrality` | LLM-as-judge (modelo diferente do julgador) | 6 |

**Pronto quando:** o baseline estiver no Langfuse e o script puder ser usado como gate.

---

## Fase 4: Gestão de prompts

| # | Tarefa | Teste antes |
|---|---|---|
| 4.1 ✅ | Criar `src/observability/prompts.py` com `get_prompt(name)`, cache e **fallback para o prompt local** | Langfuse fora do ar ⇒ usa o prompt local |
| 4.2 ✅ | Migrar os prompts do router e do judge, com a label `production` (`src/prompts/defaults.py` + `scripts/langfuse_push_prompts.py`) | — |
| 4.3 ✅ | Ligar cada generation à versão do prompt usada (`LLMClient.chat(prompt=...)`) | Generation recebe o `prompt_client`; sem prompt, nada é passado |
| 4.4 ✅ | Documentar o fluxo de mudança de prompt: nova versão → label `staging` → experiment → promoção para `production` (`docs/prompt_workflow.md`) | — |

---

## Fase 5: CI/CD

| # | Tarefa |
|---|---|
| 5.1 | `.github/workflows/ci.yml`: `uv sync --frozen` → `pytest` com tracing desligado (`LANGFUSE_TRACING_ENABLED=false`) → build das imagens com a tag do commit → push para o GHCR |
| 5.2 | `eval.yml`: roda o golden experiment e bloqueia o merge se não atingir o limiar |
| 5.3 | CD: `overlays/prod` com deploy por ArgoCD |

```
PR   ──► pytest ──► build (tag = git sha) ──► push GHCR ──► golden experiment (gate)
main ──► overlays/prod ──► ArgoCD sincroniza o cluster
```

---

## Fase 6: Avaliação online e feedback

| # | Tarefa |
|---|---|
| 6.1 | Criar `POST /feedback` (trace_id + 👍/👎) que grava um score no Langfuse, e colocar os botões no frontend |
| 6.2 | Configurar no Langfuse um avaliador LLM-as-judge de **neutralidade** (regra 6) sobre uma amostra de 10% dos traces, usando um modelo diferente do julgador |
| 6.3 | Montar dashboards de distribuição de vereditos, latência e fallback. Instalar o `kube-prometheus-stack` para métricas de infraestrutura |
| 6.4 | Usar uma fila de anotação para os traces ruins, que viram candidatos ao `golden_dataset_v2` |

---

## Deploy no Azure e LLM local (Qwen 2.5) via túnel

**Decisão:** o cluster (AKS) roda na Azure e o Ollama roda no MacBook Air M4 (24 GB), exposto por túnel. Custo de inferência: zero.

```
Pods no AKS ──HTTPS + Bearer──► URL do túnel ──► proxy com chave (Mac) ──► Ollama (localhost:11434)
```

**Por que assim:**
- A VM de 8 GB do plano estudantil só comporta o `qwen2.5:7b` (e no limite), e não o `14b` usado pelo judge. O M4 com 24 GB roda os dois com folga, com aceleração Metal.
- Não há GPU gratuita no Azure. Os créditos de estudante (cerca de US$ 100, a confirmar) ficam reservados ao cluster.
- Alternativas avaliadas e descartadas por ora: Droplet da DigitalOcean (crédito do Student Pack), Oracle Always Free (reduzido para 2 OCPUs / 12 GB em jun/2026 e com falta de capacidade frequente) e Colab/Kaggle (sessões expiram e a URL muda).

**Pontos de atenção:**
1. **Segurança:** o Ollama não tem autenticação. O túnel nunca deve apontar direto para ele. Colocar um proxy (Caddy) que exige `Authorization: Bearer` e fazer o `LLMClient` enviar o header quando existir `OLLAMA_API_KEY` (com teste unitário antes, regra 7). A chave vai num `Secret` do Kubernetes, nunca no Git.
2. **URL do túnel:** o quick tunnel do Cloudflare muda a cada reinício, e `OLLAMA_BASE_URL` no ConfigMap precisa acompanhar. URL fixa exige ngrok com domínio estático ou Cloudflare com domínio próprio.
3. **Disponibilidade:** o serviço só funciona com o Mac ligado, na tomada e sem repouso (`caffeinate -d`). Serve para demo e avaliação, não para produção.
4. **Fallback:** se o Ollama estiver inacessível, o `LLMClient` cai para o Groq (Llama, não Qwen), o que muda o comportamento. Registrar `used_fallback` no trace (Fase 2) e decidir se o fallback fica ligado nos serviços (`FALLBACK_PROVIDER`).
5. **Timeouts:** com o túnel, a latência aumenta. Revisar os timeouts do router (hoje 30 s) e do judge (60 s).
6. **Cluster local:** enquanto o cluster for o do Docker Desktop, o ConfigMap continua com `host.docker.internal:11434` e o túnel não é necessário.

**Tarefas (a executar depois das fases 0 e 1):**

| # | Tarefa | Teste antes (TDD) |
|---|---|---|
| D.1 | `LLMClient` envia `Authorization: Bearer` ao Ollama quando `OLLAMA_API_KEY` está definida (chat e generate) | Com chave ⇒ header presente. Sem chave ⇒ nenhum header |
| D.2 | Escolher o túnel (Cloudflare Tunnel recomendado) e instalar `cloudflared` e `caddy` | — |
| D.3 | `Caddyfile` com validação do Bearer e `scripts/start_ollama_tunnel.sh` que sobe proxy e túnel | — |
| D.4 | `Secret` `factcheck-ollama` (`OLLAMA_API_KEY`) e `OLLAMA_BASE_URL` no ConfigMap do overlay do AKS | — |
| D.5 | Criar o AKS (nível gratuito do control plane, um nó pequeno), conectar com `az aks get-credentials` e aplicar `overlays/dev` | — |
| D.6 | Rodar o golden dataset contra o cluster e comparar latência com o modo local | — |

**Decisões em aberto:** qual túnel usar (Cloudflare ou ngrok), se o fallback para o Groq fica ligado e se o registry será o GHCR ou o ACR.

---

## Fase 7: Unificação do fluxo do frontend com o router (Docker e Kubernetes)

**Objetivo:** o frontend passa a usar o mesmo pipeline que vai para o Kubernetes (claim → guardrails → router → tool → judge → guardrails), e o fluxo duplicado do `src/api` deixa de existir.

**Estado atual (verificado):**
- O frontend (Vite/React, `frontend/`) chama `/api/suggestions` e `/api/check` por um proxy de desenvolvimento. Não há Dockerfile nem manifest do frontend e do `src/api`.
- O `src/api` responde com `FactCheckingGuardrails.evaluate`, que usa ramos fixos no código (regras institucionais, cota, TSE) e **não** passa pelo router, pelas tools de dados nem pelo judge.
- O contrato do frontend (`verdict`, `text`, `subdetails`, `sources`, `rule_matched`, `audit_passed`, `audit_note`) é diferente do `CheckClaimResponse` do router (`veredito`, `justificativa`, `fontes_primarias`, `trace_id`...).
- O catálogo de tools do router tinha 6 tools e **não incluía as tools de regra institucional**; elas foram adicionadas (tarefa 7.1, feita antes da Fase 3). Com isso, o router atende claims normativas pelas tools da base curada (regra 4), com enums fechados de tópico, fonte e tipo de dado.

| # | Tarefa | Teste antes (TDD) |
|---|---|---|
| 7.1 ✅ | Incluir `check_institutional_rule` e `check_data_source_coverage` no catálogo e no `execute_tool` do router, separadas das tools de dado (regra 4) | Despacho de cada tool. Claim normativa não usa dado transacional |
| 7.2 | Definir o contrato único. Preferência: um adaptador no router que devolve o formato do frontend, mantendo o `CheckClaimResponse` com `trace_id` | Contrato da resposta, incluindo os 3 vereditos e `VERIFICADO` |
| 7.3 | Levar para o router o que só existe no `src/api`: `/api/suggestions` e `/api/health` | Mesmos testes de `tests/test_api.py` contra o novo serviço |
| 7.4 | Passar as 30 claims do golden dataset pelo fluxo unificado (portão da regra 5), comparando com o resultado atual do `src/api` | `test_guardrails_e2e` verde no novo fluxo antes de remover o antigo |
| 7.5 | Dockerfile do frontend (build estático servido por nginx, com proxy de `/api` para o `router-service`) e entrada no `docker-compose.yml` | Build da imagem no CI |
| 7.6 | Manifests do frontend em `k8s/base` (Deployment, Service e Ingress) e o router como `ClusterIP` atrás dele, com os overlays `dev` e `prod` | `test_k8s_manifests.py` estendido |
| 7.7 | Frontend gera e envia `session_id` por conversa (também deslogado) e `user_id` só quando houver login, e guarda o `trace_id` de cada resposta para o feedback | Teste do cliente: sem ids, a requisição continua válida |
| 7.8 | Remover do `src/api` a lógica duplicada (ramos fixos do `FactCheckingGuardrails.evaluate`) depois que a 7.4 passar | Suíte inteira verde |

**Pronto quando:** o frontend em Docker e no Kubernetes fala apenas com o router, existe um único caminho de checagem, as 30 claims passam nele e o `trace_id` chega ao frontend (pré-requisito do `POST /feedback` da Fase 6).

---

## Ordem e dependências

```
F0 ──► F1 ──► F2 ──► F3 ──► F5
              │      └────► F4
              └───────────► F6
F2 + F3 ──► F7 (unificação do frontend; F6 depende do trace_id que a F7 leva ao frontend)
```

As fases 0 e 1 podem andar em paralelo, com pessoas diferentes do grupo. A fase 2 precisa das duas prontas.

## Ferramentas

| Ferramenta | Papel | Prioridade |
|---|---|---|
| Langfuse (SDK Python v3 + Helm) | tracing, prompts, datasets, evals | essencial |
| GitHub Actions + GHCR | CI, build e registry | essencial |
| Kustomize | config por ambiente | essencial |
| Helm | instalar o Langfuse e a stack de observabilidade | essencial |
| ArgoCD | deploy GitOps | recomendado |
| kube-prometheus-stack (Prometheus + Grafana) | métricas de infra | recomendado |
| Sealed Secrets | segredos versionáveis no Git | recomendado |
| k9s | operar o cluster no dia a dia | conveniência |

## Decisões em aberto

| Decisão | Recomendação | Alternativa |
|---|---|---|
| Onde roda o LLM | Ollama no MacBook M4 via túnel (ver seção "Deploy no Azure e LLM local") | VM com CPU no Azure/DigitalOcean usando crédito de estudante |
| Langfuse no desenvolvimento | Langfuse Cloud (free tier) no dia a dia e self-hosted no cluster como "prod", por causa do peso do ClickHouse no Docker Desktop | Self-hosted em todos os ambientes |
| LLM no CI | Groq (o fallback que já existe no projeto) no job de avaliação | Runner self-hosted com Ollama |
| CD | ArgoCD, se o objetivo incluir mostrar GitOps | `kubectl apply -k` disparado manualmente no Actions |
