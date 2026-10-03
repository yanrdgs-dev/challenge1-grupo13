# Feature Specification: Resolução Canônica de Proposições Legislativas (`resolve_proposition`)

**Feature Branch**: `002-resolve-proposition`

**Created**: 2026-10-01

**Status**: Draft

**Input**: User description: "### 2.2 `resolve_proposition` 🟡 - Identificação e resolução canônica de matérias e proposições legislativas na Câmara dos Deputados, Senado Federal e Congresso Nacional via dados abertos e busca na ementa."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Resolução Direta por Identificadores Formais (Priority: P1)

Como Agente Roteador de Fact-Checking, quero resolver uma matéria legislativa citada formalmente por tipo, número e ano (ex.: "PL 2630/2020", "PEC 45/2019") para seu identificador canônico oficial na respectiva Casa Legislativa, para que ferramentas de votação nominal e tramitação possam consultar os dados exatos da matéria sem ambiguidades.

**Why this priority**: Esta é a capacidade primária exigida pelo Princípio II da Constituição. Nenhuma ferramenta de votação pode ser invocada com texto livre de proposições; a obtenção do `id_proposicao` oficial é pré-requisito bloqueante para verificar qualquer posicionamento de parlamentares.

**Independent Test**: Pode ser testada de forma autônoma fornecendo `casa="camara"`, `sigla_tipo="PL"`, `numero=2630`, `ano=2020`. O sistema deve retornar o registro canônico exato da matéria com `id_proposicao` oficial, ementa completa e `ambiguous: false`.

**Acceptance Scenarios**:

1. **Given** uma matéria com tipo, número e ano válidos (ex.: PL 2630 de 2020 na Câmara), **When** a resolução é solicitada com `casa="camara"`, `sigla_tipo="PL"`, `numero=2630`, `ano=2020`, **Then** o sistema retorna `id_proposicao` correspondente, ementa oficial, dados cadastrais da matéria e `ambiguous: false`.
2. **Given** uma matéria do Senado Federal formalmente identificada (ex.: PEC 45 de 2019 no Senado), **When** a resolução é solicitada com `casa="senado"`, `sigla_tipo="PEC"`, `numero=45`, `ano=2019`, **Then** o sistema retorna o identificador oficial do Senado com `ambiguous: false`.

---

### User Story 2 - Resolução por Nome Popular ou Tema na Ementa (Priority: P2)

Como Agente Roteador de Fact-Checking, quero que o sistema identifique a proposição legislativa quando a alegação cita apenas seu nome popular, apelido ou tema central (ex.: "PL das Fake News", "Marco Temporal", "Reforma Tributária"), localizando a matéria oficial e retornando seus dados canônicos.

**Why this priority**: No discurso público e nas redes sociais, alegações raramente utilizam o número formal de protocolo, referindo-se a projetos de lei por apelidos ou temas políticos centrais.

**Independent Test**: Pode ser testada consultando termos consagrados como `termo_busca="Marco Temporal"` acompanhado de `casa="camara"` e `ano=2023`. O sistema deve encontrar e resolver para o projeto correspondente com `ambiguous: false`.

**Acceptance Scenarios**:

1. **Given** uma busca por nome popular inequívoco associado a um tema (ex.: "PL das Fake News" ou "Marco Temporal"), **When** a resolução é executada com `termo_busca`, **Then** o sistema analisa as ementas oficiais e retorna a proposição canônica correspondente com `ambiguous: false`.
2. **Given** um termo de busca combinado com ano (ex.: `termo_busca="Reforma Tributária"`, `ano=2023`, `casa="senado"`), **When** a resolução é executada, **Then** o sistema filtra matérias daquele ano e identifica a proposição principal em discussão.

---

### User Story 3 - Detecção de Ambiguidade em Claims Vagas para Decisão de Inconclusivo (Priority: P3)

Como Agente Roteador de Fact-Checking, quero que o sistema detecte quando uma busca textual por tema genérico ou subespecificado corresponde a múltiplas proposições concorrentes sem desambiguação clara, retornando `ambiguous: true` com a lista de candidatos, para que o agente possa determinar que a alegação é subespecificada e emitir veredito `INCONCLUSIVO`.

**Why this priority**: Atende diretamente aos Casos 26 e 30 do Golden Dataset e ao Princípio III da Constituição. Alegações vagas sobre "proposta polêmica de segurança pública" ou "projeto da área fiscal" não podem ter um projeto inventado ou escolhido arbitrariamente.

**Independent Test**: Pode ser testada submetendo termos genéricos sem número formal (ex.: `casa="senado"`, `termo_busca="segurança pública"`). O sistema deve indicar `ambiguous: true`, com `id_proposicao: None` e o array `candidatos` preenchido com as matérias encontradas.

**Acceptance Scenarios**:

1. **Given** uma busca por tema genérico que retorna múltiplos projetos equivalentes sem distinção clara, **When** a resolução é executada, **Then** o sistema retorna `ambiguous: true`, `id_proposicao: None` e lista os candidatos encontrados no campo `candidatos`.
2. **Given** um termo de busca que não retorna nenhuma proposição na Casa Legislativa, **When** a resolução é executada, **Then** o sistema retorna `ambiguous: false`, `id_proposicao: None`, `ementa: None` e `candidatos: []`.

---

### Edge Cases

- **Proposições que tramitam entre casas com numerações distintas**: Um projeto aprovado na Câmara com um número recebe outra numeração ao ingressar no Senado. O sistema deve exigir o parâmetro `casa` para evitar ambiguidades de contexto federativo.
- **Falha de comunicação ou indisponibilidade de serviço externo**: Como o sistema lida com instabilidade temporária nas fontes públicas de dados legislativos? O sistema deve aplicar timeout rigoroso e retornar falha estruturada sem derrubar a execução do pipeline de fact-checking.
- **Variações de grafia em siglas de proposição ("PL", "P.L.", "Projeto de Lei")**: O sistema deve normalizar a sigla para o formato padrão aceito pelo serviço legislativo.
- **Termo de busca inexistente ou aleatório**: Retorno seguro de não encontrado, sem aproximações forçadas.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O sistema DEVE fornecer funcionalidade de resolução de proposições recebendo obrigatoriamente a Casa Legislativa (`casa`: `"camara"`, `"senado"`, `"congresso"`).
- **FR-002**: O sistema DEVE suportar busca direta determinística através da combinação de tipo (`sigla_tipo`), número (`numero`) e ano (`ano`).
- **FR-003**: O sistema DEVE suportar busca textual temático-semântica através de `termo_busca` quando número e ano não estiverem disponíveis na alegação.
- **FR-004**: O sistema DEVE normalizar termos textuais de entrada, removendo acentos, padronizando caixa alta/baixa e tratando pontuações em siglas regimentais (ex.: "P.E.C." -> "PEC").
- **FR-005**: O sistema DEVE retornar os dados canônicos da matéria legislativa localizada: identificador institucional da proposição (`id_proposicao`), tipo formal (`sigla_tipo`), número, ano de apresentação, texto da ementa oficial e casa legislativa de referência.
- **FR-006**: O sistema DEVE sinalizar explicitamente a ocorrência de ambiguidade (`ambiguous: true`) quando uma busca textual resultar em múltiplos candidatos viáveis sem um claro vencedor de correspondência, preenchendo a lista `candidatos` com os dados resumidos de cada proposição (Princípio III da Constituição).
- **FR-007**: O sistema DEVE indicar ausência de correspondência estruturada (`id_proposicao: None`, `ambiguous: false`, `candidatos: []`) quando nenhuma matéria for localizada acima do limiar aceitável de correspondência.
- **FR-008**: O sistema DEVE operar com controle estrito de tempo de espera (timeout curto de até 5 segundos) e tratamento de falhas em integrações externas, garantindo que testes unitários funcionem 100% com dados simulados/mockados sem dependência de rede (Princípio VIII da Constituição).
- **FR-009**: O sistema DEVE manter integridade de identificação institucional para que o identificador retornado possa ser utilizado imediatamente por ferramentas subsequentes de votações nominais da Câmara e Senado.

### Key Entities *(include if feature involves data)*

- **Proposição Legislativa Canônica**:
  Representa a matéria legislativa oficial em tramitação ou já apreciada. Atributos: identificador numérico institucional (`id_proposicao`), sigla do tipo de proposição (`sigla_tipo`), número sequencial oficial (`numero`), ano de proposição (`ano`), ementa resumida descritiva e casa legislativa (`casa`).
- **Resposta de Resolução de Proposição**:
  Estrutura retornada ao término da consulta. Atributos: `id_proposicao`, `sigla_tipo`, `numero`, `ano`, `ementa`, `casa`, flag booleana de ambiguidade (`ambiguous`) e lista de candidatos concorrentes (`candidatos`).
- **Candidato a Proposição**:
  Resumo de proposição concorrente contido na lista de alternativas em caso de ambiguidade, contendo identificador, sigla, número, ano e ementa resumida.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Atingir 100% de precisão na identificação direta de matérias com tipo, número e ano especificados (ex.: PL 2630/2020 da Claim 4 do Golden Dataset).
- **SC-002**: Atingir 100% de taxa de detecção de ambiguidade (`ambiguous: true`) em buscas por termos temáticos genéricos (ex.: "segurança pública" ou "área fiscal", conforme Claims 26 e 30 do Golden Dataset).
- **SC-003**: Resolver com sucesso para a proposição correta em termos populares consagrados (ex.: "PL das Fake News", "Marco Temporal") em tempo de resposta inferior a 2 segundos em condições normais de consulta.
- **SC-004**: Garantir 0% de quebras ou exceções não tratadas decorrentes de instabilidades de rede ou timeouts em fontes externas de dados.
- **SC-005**: Garantir 100% de cobertura nos 4 quadrantes de teste unitário com isolamento offline absoluto (Princípio VIII da Constituição).

## Assumptions

- A Câmara dos Deputados e o Senado Federal disponibilizam endpoints públicos de consulta de proposições em suas plataformas de dados abertos.
- Alegações que citam eventos futuros sobre projetos legislativos (como a Claim 28 do Golden Dataset) ou que permanecem com ambiguidade não resolvida serão direcionadas pelo Agente Roteador para o veredito `INCONCLUSIVO`.
- As siglas regimentais mais frequentes incluem PL, PEC, MPV, PDL, PLP, PDC e PRS.
