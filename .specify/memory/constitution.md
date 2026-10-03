<!--
### Sync Impact Report
- Version change: 0.0.0 (unratified template) → 1.0.0
- List of modified principles:
  - [PRINCIPLE_1_NAME] → I. Veredito Estritamente Baseado em Evidência Rastreável
  - [PRINCIPLE_2_NAME] → II. Resolução Obrigatória de Entidades Canônicas
  - [PRINCIPLE_3_NAME] → III. Claims Subespecificadas Resultam em Inconclusivo
  - [PRINCIPLE_4_NAME] → IV. Separação entre Dado Transacional e Regra Institucional
  - [PRINCIPLE_5_NAME] → V. Golden Dataset como Portão de Aceite Absoluto
- Added principles / sections:
  - ### VI. Neutralidade Absoluta e Isenção de Viés
  - ### VII. Test-Driven Development (TDD) Inegociável
  - ### VIII. Isolamento e Cobertura Unitária Rigorosa de Tools
  - ### IX. Commits Convencionais com Escopo Semântico
  - ### X. Stack Tecnológica Unificada em Python
  - SECTION_2_NAME → Restrições de Arquitetura e Engenharia de Dados
  - SECTION_3_NAME → Fluxo de Desenvolvimento e Portões de Qualidade
- Removed sections: None
- Follow-up TODOs: None
-->

# Fact-Checking Político Brasileiro Constitution

## Core Principles

### I. Veredito Estritamente Baseado em Evidência Rastreável
O agente NUNCA deve responder `VERDADEIRO` ou `FALSO` a partir da memória paramétrica do
modelo (LLM). Todo e qualquer veredito final DEVE citar explicitamente o retorno estruturado
de uma tool específica e a respectiva fonte primária (dataset oficial, API pública ou base
normativa curada). Se as tools não retornarem evidência suficiente para comprovar ou refutar
a alegação, o veredito DEVE ser obrigatoriamente `INCONCLUSIVO` — palpites ou inferências
especulativas são estritamente proibidos.
*Rationale*: A credibilidade de um sistema de fact-checking político repousa na auditabilidade
integral de cada conclusão até sua fonte primária institucional.

### II. Resolução Canônica Obrigatória de Entidades
Nenhuma tool de dados ou API externa PODE ser chamada utilizando texto livre para nomes de
parlamentares ou proposições legislativas. Toda entidade DEVE ser previamente resolvida por uma
tool de resolução canônica (texto → ID canônico, como `resolve_politician` ou
`resolve_proposition`) para evitar falsos positivos decorrentes de homônimos ou correspondências
inventadas. Junções de identidade NUNCA devem depender de CPF; joins DEVEM utilizar exclusivamente
nome normalizado + UF/cargo.
*Rationale*: Erros em atribuição de autoria ou homonímia desmoralizam a checagem; além disso,
o uso de CPF viola práticas de privacidade e não é chave confiável nas fontes públicas abertas.

### III. Claims Subespecificadas Resultam em Inconclusivo
Alegações subespecificadas, vagas ou não ancoradas DEVEM ser avaliadas imediatamente como
`INCONCLUSIVO`, com justificativa explícita, ANTES da execução de qualquer tool de dados.
Constituem gatilhos mandatórios de veredito inconclusivo:
1. Ausência de entidade identificável e passível de resolução canônica;
2. Referências temporais relativas não ancoráveis a uma data ou legislatura precisa;
3. Atribuição exclusiva a fontes de baixa credibilidade (redes sociais, boatos, "imprensa comenta");
4. Alegações sobre eventos futuros ou fatos ainda não consumados.
O agente NUNCA deve inferir parâmetros arbitrários ou forçar correspondências para gerar respostas.
*Rationale*: Tentar responder alegações incompletas induz o modelo a alucinar premissas que
não constavam na formulação original do usuário.

### IV. Separação entre Dado Transacional e Regra Institucional
DEVE existir estrita separação entre tools de consulta a dados transacionais e tools de
conhecimento normativo:
- Claims sobre fatos ocorridos ("o que aconteceu": despesas, votações, frequência, rankings)
  DEVEM ser resolvidas por tools que consultam registros transacionais auditados.
- Claims sobre legalidade, legitimidade ou funcionamento ("o que é permitido/como funciona":
  regramento da CEAP, regimentos internos, rito legislativo) DEVEM ser resolvidas por uma base
  normativa curada e versionada (`check_institutional_rule`).
O agente NUNCA deve inferir silenciosamente legalidade institucional a partir de dados
transacionais sem verificar a base normativa aplicável.
*Rationale*: O fato de um gasto ou evento ter ocorrido em base de dados não significa que seja
regimentalmente lícito ou autorizado; dados não substituem normas.

### V. Golden Dataset como Portão de Aceite Absoluto
O arquivo `golden_dataset_v1.json` (30 alegações calibradas cobrindo `VERDADEIRO`, `FALSO` e
`INCONCLUSIVO`) é o portão de aceite mandatório para qualquer tool ou pipeline de agente.
Nenhuma funcionalidade é considerada concluída sem atingir 100% de conformidade nas claims
de referência pertinentes. Novas alegações adicionadas ao dataset exigem implementação prévia
da cobertura correspondente nas tools antes de qualquer merge na branch principal.
*Rationale*: Um conjunto fixo e curado de casos reais impede regressões funcionais e garante
a acurácia de vereditos entre iterações do sistema.

### VI. Neutralidade Absoluta e Isenção de Viés
O agente DEVE operar sob estrita neutralidade axiológica, sem viés de confirmação em qualquer
direção. O sistema NÃO PODE apresentar viés de refutação prévia (tendência ao `FALSO`, ainda que
checagens históricas desmintam mais do que confirmem) e NÃO PODE ter viés de validação da premissa
do usuário. A linguagem da resposta final DEVE ser estritamente descritiva, objetiva e despida
de adjetivos valorativos, independentemente do veredito obtido.
*Rationale*: A confiança do público no fact-checking depende de isenção técnica e linguagem
imparcial em qualquer circunstância.

### VII. Test-Driven Development (TDD) Inegociável
O desenvolvimento orientado a testes (TDD) é OBRIGATÓRIO e inegociável em todo o repositório.
Nenhuma tool, extrator ou lógica de orquestração DEVE ser codificada antes do teste unitário
que a especifica. O ciclo Red-Green-Refactor DEVE ser rigorosamente cumprido:
1. Red: Criar o teste unitário que falha;
2. Green: Implementar o código mínimo estritamente necessário para o teste passar;
3. Refactor: Refatorar o código mantendo a suíte de testes verde.
Pull requests contendo código funcional sem testes associados pré-existentes DEVEM ser rejeitados.
*Rationale*: Garante foco no contrato da interface, cobertura consistente e ausência de código
morto ou não verificado.

### VIII. Isolamento e Cobertura Unitária Rigorosa de Tools
Toda tool do catálogo DEVE possuir uma suíte de testes unitários isolados cobrindo, no mínimo,
quatro cenários fundamentais:
1. Caminho feliz (entidade resolvida e dados retornados com sucesso);
2. Entidade não encontrada / registro inexistente;
3. Entidade ambígua / homônimos detectados (quando aplicável);
4. Falha de rede simulada (timeouts, HTTP 4xx/5xx mockados para tools com integração externa).
Testes unitários NUNCA devem efetuar requisições reais de rede; dependências de API externa DEVEM
ser completamente simuladas via mocks. As claims do golden dataset servem de inspiração para
casos de teste, mas NÃO substituem a suíte unitária isolada da tool.
*Rationale*: Previne que testes quebrem por instabilidade de rede e assegura robustez operacional
em condições adversas.

### IX. Commits Convencionais com Escopo Semântico
Todos os commits DEVEM seguir estritamente o padrão Conventional Commits no formato
`tipo(escopo): descrição`. Tipos válidos: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`.
O escopo DEVE indicar o módulo ou domínio impactado (ex.: `feat(tools): adiciona resolve_politician`,
`test(gastos): cobre check_parliamentary_expenses`). Commits de testes escritos antes do código
de produção (etapa Red do TDD) DEVEM utilizar o prefixo `test:`, mesmo que a funcionalidade
ainda não esteja implementada.
*Rationale*: Mantém o histórico do repositório auditável, viabiliza changelogs automatizados e
registra explicitamente a disciplina de TDD.

### X. Stack Tecnológica Unificada em Python
Toda a base de código (tools, agentes, orquestração, pipelines e clientes HTTP) DEVE ser
desenvolvida exclusivamente em Python. Bibliotecas previamente padronizadas no projeto DEVEM ser
obrigatoriamente reaproveitadas:
- Consultas analíticas locais sobre arquivos Parquet: `Polars` e `DuckDB` (conforme `docs/data_schemas.md`);
- Clientes HTTP assíncronos/síncronos: `httpx`;
- Testes unitários e mocks: `pytest` e `pytest-mock`.
É estritamente proibido introduzir stacks paralelas ou bibliotecas concorrentes para as mesmas
finalidades sem atualização prévia desta constituição.
*Rationale*: Padronização técnica reduz a complexidade do ambiente, evita dependências redundantes
e garante máxima interoperabilidade com os pipelines de dados existentes.

## Restrições de Arquitetura e Engenharia de Dados

O projeto opera sob uma arquitetura híbrida de dados projetada para maximizar velocidade local e
manter custos e latência controlados:

1. **Repositório de Dados Local**:
   - Dados históricos de despesas (CEAP/CEAPS), candidaturas e proposições legislativas residem
     localmente em formato Parquet (`data/processed/` ou `datasets/`).
   - Consultas sobre Parquet DEVEM ser executadas prioritariamente via Polars ou DuckDB, conforme
     especificado em `docs/data_schemas.md`.
2. **Fronteira de Rede**:
   - Chamadas a APIs externas ao vivo são restritas a votações da Câmara/Senado e eventuais
     endpoints de desambiguação remota.
   - Qualquer consulta transacional com base histórica disponível localmente DEVE ser resolvida
     offline sem chamadas externas.
3. **Privacidade e Identidade**:
   - É vedado o armazenamento, coleta ou cruzamento de dados pessoais sensíveis (CPF).
   - A unicidade de agentes políticos repousa sobre chaves canônicas institucionais
     (`SQ_CANDIDATO`, `ideCadastro`, `COD_SENADOR`) unificadas por nome normalizado e UF/cargo.

## Fluxo de Desenvolvimento e Portões de Qualidade

Todo ciclo de entrega no repositório DEVE satisfazer os seguintes portões de qualidade:

1. **Fluxo Red-Green-Refactor**:
   - O desenvolvedor DEVE registrar primeiramente um commit com a suíte de testes unitários falhando
     (`test(...)`).
   - Em seguida, implementa o código necessário para torná-la verde (`feat(...)` ou `fix(...)`).
   - Por fim, realiza refatorações pontuais preservando a integridade dos testes (`refactor(...)`).
2. **Matriz Mínima de Testes por Tool**:
   - Caminho feliz;
   - Entidade ausente;
   - Desambiguação / homônimos;
   - Resiliência / mocks de falha externa.
3. **Portão de Regressão (Golden Dataset)**:
   - Execução de testes ponta a ponta validando as 30 alegações do arquivo `golden_dataset_v1.json`.
   - Nenhuma taxa de regressão em vereditos consolidados é tolerada.
4. **Revisão de Código**:
   - PRs sem testes unitários ou sem conformidade com as convenções de commit DEVEM ser reprovados.

## Governance

Esta Constituição representa a autoridade máxima de governança do projeto, sobrepondo-se a
solicitações informais, conveniências pontuais de implementação ou premissas não formalizadas.

1. **Procedimento de Emenda**:
   - Qualquer alteração nos princípios, requisitos de stack ou regras institucionais DEVE ser
     formalizada através de proposta de emenda constitucional (Issue / RFC).
   - A emenda DEVE conter justificativa técnica detalhada e avaliação de impacto nas ferramentas
     existentes e nas 30 claims do `golden_dataset_v1.json`.
   - Nenhuma emenda pode ser aprovada sem revisão e consentimento formal dos mantenedores.
2. **Política de Versionamento Semântico**:
   - **MAJOR**: Alterações que removam princípios, invertam regras de veredito ou modifiquem
     drasticamente os portões de aceite;
   - **MINOR**: Inclusão de novos princípios, ferramentas obrigatórias ou ampliações materiais
     nas diretrizes de engenharia;
   - **PATCH**: Ajustes redacionais, correções tipográficas e clarificações que não alterem o escopo
     mandatório.
3. **Auditoria Contínua de Conformidade**:
   - Todos os Pull Requests e revisões de código DEVEM auditar o cumprimento explícito dos
     dez princípios fundamentais antes do merge.

**Version**: 1.0.0 | **Ratified**: 2026-10-01 | **Last Amended**: 2026-10-01
