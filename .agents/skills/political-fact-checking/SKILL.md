---
name: political-fact-checking
description: Regras inegociáveis, diretrizes de arquitetura, fluxo TDD e constituição para o desenvolvimento do agente de fact-checking político brasileiro. Use sempre ao implementar ou modificar tools, agentes, testes, orquestração, pipelines de dados ou fluxos de verificação de claims.
---

# Constituição e Diretrizes do Agente de Fact-Checking Político Brasileiro

Este documento estabelece as regras inegociáveis e diretrizes arquiteturais para qualquer implementação ou alteração neste repositório.

---

## 1. Os 10 Princípios Inegociáveis

1. **Nenhum veredito sem evidência rastreável:**
   - O agente **nunca** responde `VERDADEIRO` ou `FALSO` a partir da memória paramétrica do LLM.
   - Todo veredito final precisa citar expressamente o resultado de uma tool específica e a respectiva fonte primária (dataset oficial, API pública ou base normativa curada).
   - Se nenhuma tool retornou evidência suficiente, o veredito obrigatório é `INCONCLUSIVO` — nunca um palpite ou aproximação.

2. **Resolução de entidade é obrigatória antes de qualquer consulta de dado:**
   - Nenhuma tool de dado ou chamada de API pode receber nome de parlamentar ou de proposição em texto livre diretamente da claim.
   - A entidade precisa obrigatoriamente passar primeiro por uma tool de resolução (`nome/texto` → `ID canônico`), prevenindo erros por homônimos, apelidos ou correspondências inventadas.
   - O join de identidade **nunca** pode depender de CPF; deve utilizar exclusivamente **nome normalizado + UF/cargo**.

3. **Claims subespecificadas resultam em INCONCLUSIVO, não em parâmetro inventado:**
   - Se a alegação não nomeia uma entidade resolvível, usa referência temporal relativa não ancorável (ex.: "recentemente", "no ano passado" sem contexto de data de emissão), cita fonte de baixa credibilidade (redes sociais, boatos, "comentários na imprensa") ou descreve evento futuro/ainda não ocorrido:
     - O agente deve identificar essa condição **antes** de disparar qualquer tool de dados.
     - Devolver imediatamente `INCONCLUSIVO` com a justificativa transparente, sem forçar correspondência ou inventar parâmetros.

4. **Separação entre tool de dado transacional e tool de regra institucional:**
   - **Claims sobre "o que aconteceu"** (valores, gastos, histórico de votos, rankings): resolvidas exclusivamente por tools que consultam dados reais/transacionais.
   - **Claims sobre "o que é permitido / como funciona"** (regras, regimentos internos, normas legais, procedimentos): resolvidas exclusivamente por consulta a uma base de conhecimento curada e versionada.
   - É expressamente proibido inferir regras institucionais silenciosamente a partir de dados transacionais sem checar a fonte normativa.

5. **O Golden Dataset é o portão de aceite:**
   - Nenhuma tool ou fluxo de agente é considerado pronto sem passar em 100% das 30 alegações presentes em [golden_dataset_v1.json](file:///Users/aluno2/Documents/challenge1-grupo13/golden_dataset_v1.json), cobrindo com precisão os veredictos `VERDADEIRO`, `FALSO` e `INCONCLUSIVO`.
   - Quaisquer alegações adicionadas ao dataset exigem cobertura de tool correspondente antes do merge.

6. **Neutralidade de veredito:**
   - O agente não pode ter viés de confirmação em nenhuma direção: nem tendendo a `FALSO` (mesmo sabendo que agências de checagem frequentemente publicam mais desmentidos que confirmações), nem tendendo a validar a alegação do usuário.
   - A linguagem do veredito e da justificativa final deve ser estritamente técnica, impessoal e neutra, independentemente do resultado.

7. **TDD é obrigatório e não-negociável:**
   - Nenhuma tool ou lógica de agente é escrita antes do teste automatizado que a especifica.
   - Ciclo obrigatório **Red-Green-Refactor**:
     1. Escrever o teste unitário falhando (Red).
     2. Implementar o código mínimo necessário para passar (Green).
     3. Refatorar o código mantendo os testes verdes (Refactor).
   - Pull Requests que adicionem código sem teste correspondente prévio serão rejeitados.

8. **Suíte de teste unitário obrigatória por tool:**
   - Toda tool do catálogo deve possuir suíte de teste cobrindo minimamente:
     - **Caminho feliz:** entidade resolvida e dado encontrado com sucesso.
     - **Entidade não encontrada:** comportamento seguro quando a entidade inexiste.
     - **Entidade ambígua:** tratamento adequado de múltiplos candidatos/proposições com mesmo nome.
     - **Timeout / Erro de rede (mock):** simulação de falha de conexão/API externa sem depender de requisições de rede reais em testes unitários.
   - As claims do `golden_dataset_v1.json` servem de base para cenários de validação, mas não substituem os testes unitários isolados da tool.

9. **Padrão de commits (Conventional Commits):**
   - Mensagens de commit devem seguir o padrão: `<tipo>(<escopo>): <descrição>`.
   - Tipos permitidos: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`.
   - O escopo deve indicar com clareza o módulo afetado (ex.: `feat(tools): adiciona resolve_politician`, `test(gastos): cobre check_parliamentary_expenses`).
   - Commits de teste que antecedem a implementação (etapa Red do TDD) usam `test:` mesmo quando o código de produção ainda não existe.

10. **Stack de implementação:**
    - Toda a implementação deve ser feita em **Python**: tools, agentes, orquestração e clientes HTTP.
    - Reaproveitar as bibliotecas padronizadas no projeto:
      - **DuckDB** e **Polars** para consultas analíticas sobre Parquet/dados locais (conforme [docs/data_schemas.md](file:///Users/aluno2/Documents/challenge1-grupo13/docs/data_schemas.md)).
      - Clientes HTTP assíncronos/estruturados (`httpx`/`requests` com mocks via `pytest-mock` / `respx` / `unittest.mock`).
    - É proibido introduzir stacks paralelas para as mesmas finalidades sem atualização formal desta constituição.

---

## 2. Checklist Operacional para Desenvolvimento

Antes de submeter qualquer nova feature ou tool:

- [ ] O teste unitário foi commitado antes do código de produção? (`test(...)`)
- [ ] Foram cobertos os 4 cenários da tool (feliz, não encontrado, ambíguo, falha de rede/mock)?
- [ ] A tool de dados exige ID canônico resolvido (sem texto livre de político/proposição)?
- [ ] O join de entidades evita CPF e utiliza nome normalizado + UF/cargo?
- [ ] Alegações subespecificadas ou temporais sem âncora retornam `INCONCLUSIVO` sem invocar tools de dados?
- [ ] A resposta cita a tool executada e a fonte primária oficial?
- [ ] Os testes executam com `pytest` sem requisições HTTP reais?
- [ ] O fluxo valida os casos mapeados em `golden_dataset_v1.json`?
