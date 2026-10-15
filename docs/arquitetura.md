# Arquitetura

## 1. Visão geral (da interface à fonte dos dados)

```mermaid
flowchart LR
    user(["Usuário"]) --> web

    subgraph vm["VM Azure (Docker Compose)"]
        web["<b>Frontend Pólis</b><br/>React + nginx :80<br/>rate limit 20 req/min<br/>SSE: step, token, done"]
        router["<b>Router Service</b><br/>FastAPI<br/>/api/* e /check"]
        judge["<b>Judge Service</b><br/>FastAPI /judge"]
        parquet[("Parquets locais<br/>/srv/factcheck/data/processed<br/>CEAP, CEAPS, proposições, TSE")]
        kb[("Base normativa curada<br/>regras e fontes de dados")]
        web -->|"proxy /api/*"| router
        router -->|"evidência + alegação"| judge
        router --> parquet
        router --> kb
    end

    subgraph ext["APIs públicas ao vivo"]
        camara["Câmara dos Deputados<br/>Dados Abertos"]
        senado["Senado Federal<br/>Dados Abertos"]
    end
    router --> camara
    router --> senado

    subgraph mac["Máquina de desenvolvimento"]
        ollama["<b>Ollama</b><br/>qwen2.5:7b (roteador)<br/>qwen2.5:14b (julgador)"]
    end
    router -.->|"túnel SSH reverso :11434"| ollama
    judge -.->|"túnel SSH reverso :11434"| ollama
    groq["Groq (fallback)"]
    router -.-> groq
    judge -.-> groq

    langfuse[("<b>Langfuse</b><br/>traces, prompts<br/>production / staging / eval<br/>scores e experiments")]
    router --> langfuse
    judge --> langfuse
    web -->|"👍 / 👎 vira score no trace"| router
```

**Estratégia de LLM:** por padrão a cadeia de provedores é percorrida em ordem (Ollama, Groq, DeepSeek). Com `LLM_STRATEGY=round_robin`, cada requisição começa num provedor diferente (Ollama, Groq, DeepSeek, Ollama, ...) e, se o da vez falhar (fora do ar, limite acabou, disjuntor aberto ou teto diário), passa ao próximo da rotação. Cada chamada ao LLM é registrada no Langfuse com `model`, `provider`, `strategy` e `fallback`; o trace recebe a tag `llm_strategy:<estratégia>`.

**Deploy:** GitHub Actions faz o build das imagens (GHCR) a cada PR; depois do merge na `main`, o CD entra na VM por SSH (com aprovação do revisor), sobe a nova versão, confere `/api/health` e volta à versão anterior se falhar.

## 2. O caminho de uma alegação no roteador

```mermaid
flowchart TD
    q(["Alegação"]) --> in["Guardrails de entrada<br/>claim vazia, futuro, referência relativa,<br/>fonte de baixa credibilidade"]
    in -->|bloqueada| inc1["INCONCLUSIVO<br/>com a regra acionada"]
    in --> cat

    subgraph etapa1["Etapa 1: categoria"]
        cat{"Regra decide?<br/>sinal claro de um só tema"}
        cat -->|sim| c
        cat -->|"não"| llm1["LLM classifica em JSON<br/>(qwen2.5:7b)"]
        llm1 --> c["COTA_PARLAMENTAR<br/>PROPOSICOES<br/>ELEICOES<br/>NORMAS"]
    end

    c --> restrict["Catálogo restrito:<br/>tools da categoria + normativas"]

    subgraph etapa2["Etapa 2: escolha da tool"]
        restrict --> llm2["LLM escolhe a tool e os parâmetros<br/>(function calling)"]
        llm2 --> guards["Guardas e reparos determinísticos<br/>proposição citada → resolvedor<br/>gasto sem campanha → tools de cota<br/>tramitação e apensamento<br/>compare_candidates com 1 nome<br/>dica de tool pela redação<br/>turno dito na alegação<br/>nome do parlamentar precisa estar na alegação"]
    end

    guards -->|"nenhuma tool"| inc2["INCONCLUSIVO determinístico<br/>(o julgador não é chamado)"]
    guards --> exec["execute_tool"]

    subgraph dados["Execução (regra 2: resolver a entidade antes)"]
        exec --> resolve["Resolve o nome para o ID canônico<br/>parlamentar, candidato ou proposição"]
        resolve -->|"não resolvido ou ambíguo"| ev0["Evidência: entidade_nao_resolvida"]
        resolve --> data["Tool de dados<br/>parquet ou API"]
    end

    data --> ev["Evidência + fonte primária + data da base"]
    ev0 --> judge
    ev --> tse{"TSE sem votação<br/>publicada?"}
    tse -->|sim| inc3["INCONCLUSIVO determinístico<br/>(dados_tse_nao_atualizados)"]
    tse -->|não| judge["Julgador (qwen2.5:14b)<br/>VERDADEIRO, FALSO ou INCONCLUSIVO"]
    judge --> out["Guardrails de saída<br/>sem evidência ou sem fonte → INCONCLUSIVO<br/>fonte e data atribuídas pela tool"]
    out --> resp(["Resposta ao usuário<br/>veredito, justificativa, fontes, ferramentas, tempo"])
    inc1 --> resp
    inc2 --> resp
    inc3 --> resp
```

## 3. Tools por categoria

```mermaid
flowchart LR
    router{{"Roteador"}}

    router --> cota["<b>COTA_PARLAMENTAR</b><br/>gastos da cota (CEAP e CEAPS)"]
    router --> prop["<b>PROPOSICOES</b><br/>PL, PEC, PLN, MPV e nomes populares"]
    router --> eleicoes["<b>ELEICOES</b><br/>candidatos e campanha (TSE)"]
    router --> normas["<b>NORMAS</b><br/>o que é permitido, o que dá para consultar"]

    cota --> t1["get_top_ceap_spender"]
    cota --> t2["get_member_expenses"]
    cota --> t3["check_parliamentary_expenses"]
    cota --> t4["list_expense_categories"]
    cota --> rp["resolve_politician"]
    t1 & t2 & t3 & t4 --> d1[("CEAP Câmara e CEAPS Senado<br/>parquets 2022 a 2026")]

    prop --> p1["resolve_proposition"]
    prop --> p2["get_proposition_vote_result"]
    prop --> p3["get_proposition_tramitation_history"]
    prop --> p4["check_bill_apensamentos"]
    prop --> rp
    p1 & p2 --> d2["APIs ao vivo<br/>Câmara e Senado"]
    p3 & p4 --> d3[("Proposições<br/>parquets")]

    eleicoes --> e1["resolve_candidate"]
    eleicoes --> e2["get_election_result"]
    eleicoes --> e3["get_candidate_votes"]
    eleicoes --> e4["check_candidate_status"]
    eleicoes --> e5["check_disqualification_motive"]
    eleicoes --> e6["check_candidate_profile"]
    eleicoes --> e7["get_candidate_assets"]
    eleicoes --> e8["check_cash_and_special_assets"]
    eleicoes --> e9["verify_official_social_media"]
    eleicoes --> e10["get_campaign_finances"]
    eleicoes --> e11["get_top_campaign_finances"]
    eleicoes --> e12["compare_candidates"]
    e1 & e2 & e3 & e4 & e5 & e6 & e7 & e8 & e9 & e10 & e11 & e12 --> d4[("TSE<br/>parquets 2022, 2024 e 2026")]

    normas --> n1["check_institutional_rule"]
    normas --> n2["check_data_source_coverage"]
    n1 & n2 --> d5[("Base normativa curada<br/>versionada")]

    n1 -.->|"disponíveis em toda categoria"| cota
    n1 -.-> prop
    n1 -.-> eleicoes
```

**Regras da constituição que o desenho garante:** nenhum veredito sem evidência de uma tool com fonte primária (regra 1); a entidade é resolvida para o ID antes de qualquer consulta de dado (regra 2); claim subespecificada vira INCONCLUSIVO, sem parâmetro inventado (regra 3); dado transacional e regra institucional ficam em tools separadas (regra 4).
