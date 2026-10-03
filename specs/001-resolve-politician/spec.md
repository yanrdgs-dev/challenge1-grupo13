# Feature Specification: Resolução Canônica de Parlamentares (`resolve_politician`)

**Feature Branch**: `001-resolve-politician`

**Created**: 2026-10-01

**Status**: Draft

**Input**: User description: "### 2.1 `resolve_politician` 🟢 - Resolução e desambiguação canônica de parlamentares (nome, UF, cargo, ano) para IDs institucionais da Câmara, Senado e TSE"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Resolução Canônica Direta de Parlamentar (Priority: P1)

Como Agente Roteador de Fact-Checking, quero resolver um nome próprio de parlamentar extraído de uma alegação (seja nome civil, nome de urna ou apelido político consagrado) para seu registro canônico unificado, para que ferramentas de consulta transacional (gastos, votações, proposições) possam ser executadas com chaves institucionais exatas e sem ambiguidade.

**Why this priority**: Esta funcionalidade é a pedra fundamental do sistema de checagem. Conforme o Princípio II da Constituição do projeto, nenhuma ferramenta de dados pode ser invocada com texto livre de nomes; sem a resolução canônica determinística, nenhuma checagem dependente de dados parlamentares pode operar com confiabilidade.

**Independent Test**: Pode ser testada de forma autônoma fornecendo nomes de parlamentares federais conhecidos (com ou sem acentuação, maiúsculas/minúsculas). O sistema retorna com sucesso a entidade canônica contendo os identificadores institucionais esperados, partido, estado e sinalização de ambiguidade falsa (`ambiguous: false`).

**Acceptance Scenarios**:

1. **Given** um nome de parlamentar válido e inequívoco (ex.: "Nikolas Ferreira" ou "Tabata Amaral"), **When** a resolução é solicitada com `nome_busca`, **Then** o sistema retorna a entidade canônica única com seus identificadores institucionais correspondentes, dados cadastrais básicos e `ambiguous: false`.
2. **Given** um nome de urna ou apelido político comum de parlamentar (ex.: "Tiririca"), **When** a resolução é solicitada com `nome_busca`, **Then** o sistema associa corretamente ao perfil canônico do parlamentar respectivo, sem exigir o nome civil formal completo.

---

### User Story 2 - Detecção e Tratamento de Homônimos e Ambiguidade (Priority: P2)

Como Agente Roteador de Fact-Checking, quero que o sistema detecte quando um nome fornecido na alegação corresponde a mais de um parlamentar federal e me informe as opções alternativas, ou desambigue automaticamente caso parâmetros contextuais (UF, cargo ou ano de mandato) tenham sido fornecidos.

**Why this priority**: Evita falsos positivos graves decorrentes de homônimos na política brasileira, garantindo que despesas ou votações de um parlamentar jamais sejam atribuídas indevidamente a outro político de mesmo nome.

**Independent Test**: Pode ser testada consultando nomes compartilhados por múltiplos políticos em estados ou casas legislativas diferentes. O sistema deve indicar `ambiguous: true` quando nenhum filtro for passado, e resolver para um único registro quando `uf` ou `cargo` for especificado.

**Acceptance Scenarios**:

1. **Given** um nome compartilhado por dois ou mais parlamentares em diferentes estados sem fornecimento de filtro, **When** a resolução é executada, **Then** o sistema retorna `ambiguous: true`, com os identificadores principais nulos ou vazios e a lista `candidatos_alternativos` preenchida com as entidades correspondentes.
2. **Given** uma busca por nome ambíguo com fornecimento de UF discriminadora (ex.: `nome_busca` acompanhado de `uf="SP"`), **When** a resolução é executada, **Then** o sistema filtra os concorrentes e retorna a entidade canônica específica de São Paulo com `ambiguous: false`.
3. **Given** uma busca por nome ambíguo com fornecimento de cargo discriminador (ex.: `cargo="Senador"`), **When** a resolução é executada, **Then** o sistema desambigua com base na casa legislativa correta e retorna a entidade com `ambiguous: false`.

---

### User Story 3 - Validação de Entidades Oriundas de Ferramentas de Ranking (Priority: P3)

Como Agente Sintetizador de Fact-Checking, quero validar se uma entidade parlamentar retornada por uma consulta analítica agregada (por exemplo, o maior gastador de cota parlamentar em um período) corresponde a um parlamentar canônico real antes de emitir o veredito final da alegação.

**Why this priority**: Garante consistência de ponta a ponta na esteira de checagem, assegurando que nomes retornados por consultas transacionais sejam confirmados contra a base canônica antes de serem apresentados ao usuário final.

**Independent Test**: Pode ser testada submetendo os nomes e estados gerados por consultas analíticas agregadas (cenário de validação do Golden Dataset) e verificando se a resolução confirma a integridade da entidade.

**Acceptance Scenarios**:

1. **Given** um nome e estado retornados por uma consulta de maior gasto parlamentar, **When** a validação canônica é solicitada, **Then** o sistema confirma a identidade canônica do parlamentar com alta precisão e sem ambiguidade.
2. **Given** um termo de busca inexistente na base de parlamentares ou referente a pessoa não elegível, **When** a resolução é executada, **Then** o sistema reporta que a entidade não foi localizada, sem inventar parâmetros nem forçar aproximações espúrias.

---

### Edge Cases

- **Nomes com variações fonéticas ou pequenos erros de digitação**: Como o sistema se comporta quando o usuário omite letras duplicadas ou comete pequenos lapsos tipográficos no nome do parlamentar? O sistema deve aplicar tolerância com limite de similaridade rigoroso, priorizando precisão sobre revocação para não associar pessoas erradas.
- **Parlamentar com mandatos em casas distintas (Deputado e depois Senador)**: O sistema deve preservar a unicidade da pessoa física parlamentar, unificando seus históricos e permitindo filtragem por `cargo` ou `ano` quando relevante.
- **Texto de busca vazio ou composto apenas por caracteres especiais/espaços**: O sistema deve rejeitar a requisição de imediato com erro claro de validação de parâmetro de entrada, sem consumir processamento desnecessário.
- **Nenhum parlamentar localizado**: Quando o nome buscado não atingir o limiar de confiança, o sistema deve retornar resultado estruturado indicando ausência de correspondência (not found), permitindo ao agente avaliar a alegação como `INCONCLUSIVO`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O sistema DEVE fornecer uma funcionalidade de resolução de entidades parlamentares que receba obrigatoriamente o parâmetro textual de busca (`nome_busca`) e opcionalmente parâmetros de refinamento (`uf`, `cargo`, `ano`).
- **FR-002**: O sistema DEVE normalizar o texto de entrada antes de efetuar comparações, realizando a remoção de diacríticos/acentos, uniformização de caixa alta/baixa e eliminação de espaçamentos extras.
- **FR-003**: O sistema DEVE indexar e buscar correspondências tanto pelo nome civil de registro quanto pelo nome de urna/apelido político cadastrado formalmente perante a Justiça Eleitoral e as Casas Legislativas.
- **FR-004**: O sistema DEVE retornar os identificadores canônicos unificados do parlamentar perante a Câmara dos Deputados (`ideCadastro`), Senado Federal (`cod_senador`) e Tribunal Superior Eleitoral (`sq_candidato`).
- **FR-005**: O sistema DEVE identificar parlamentares exclusivamente por identificadores institucionais e atributos públicos (nome normalizado + UF/cargo), sendo ESTRITAMENTE VEDADO o uso, coleta, dependência ou exigência de CPF para fins de unificação ou resolução (Princípio II da Constituição).
- **FR-006**: O sistema DEVE calcular o grau de correspondência da busca e, caso múltiplos parlamentares atinjam pontuação viável sem distinção clara, DEVE sinalizar a ocorrência de ambiguidade (`ambiguous: true`) e relacionar a lista de candidatos alternativos viáveis.
- **FR-007**: O sistema DEVE utilizar os parâmetros opcionais de estado (`uf`), cargo (`cargo`) ou ano de legislatura (`ano`), quando fornecidos, para restringir o universo de candidatos e eliminar ambiguidades.
- **FR-008**: O sistema DEVE indicar de forma explícita e estruturada quando nenhuma entidade for encontrada acima do limiar de confiança, evitando correspondências forçadas que possam induzir a alucinações nas etapas seguintes de checagem.
- **FR-009**: O sistema DEVE operar de forma autônoma e local, sem depender de chamadas síncronas a serviços externos ou APIs de rede durante o ciclo de resolução.
- **FR-010**: O sistema DEVE retornar os metadados contextuais essenciais da entidade encontrada: nome civil completo, nome de urna, casa legislativa mais recente, estado (UF) de representação e partido político.

### Key Entities *(include if feature involves data)*

- **Perfil Canônico de Parlamentar**:
  Representa a entidade política unificada no âmbito federal brasileiro. Possui como atributos fundamentais: identificador eleitoral TSE (`sq_candidato`), identificador legislativo da Câmara (`ideCadastro`), identificador legislativo do Senado (`cod_senador`), nome civil completo, nome de urna, estado federativo (UF), casa legislativa de atuação e filiação partidária.
- **Resposta da Resolução Canônica**:
  Estrutura retornada ao término da consulta. Contém os dados cadastrais e identificadores da entidade resolvida, o indicador booleano de ambiguidade (`ambiguous`), uma lista de perfis de candidatos alternativos (preenchida em casos de ambiguidade) e o status do casamento (resolvido, ambíguo ou não encontrado).
- **Consulta de Resolução**:
  Estrutura de parâmetros enviada pelo Agente Roteador ou Agente Sintetizador, composta por termo textual obrigatório (`nome_busca`), sigla de estado (`uf`), cargo legislativo (`cargo`) e ano de referência (`ano`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Atingir 100% de acurácia na resolução direta de parlamentares federais presentes nas alegações de referência do benchmark oficial do projeto (`golden_dataset_v1.json`).
- **SC-002**: Identificar e sinalizar ambiguidade (`ambiguous: true`) em 100% dos casos de homônimos federais conhecidos quando nenhum parâmetro de desambiguação (UF/cargo) for informado.
- **SC-003**: Resolver com sucesso para a entidade correta em mais de 98% dos casos de nomes grafados sem acentos, com letras maiúsculas/minúsculas alternadas ou utilizando nomes de urna registrados.
- **SC-004**: Garantir taxa de 0% de falsos positivos induzidos por termos de busca aleatórios ou nomes de personalidades sem mandato federal registrado (retorno mandatório de não encontrado).
- **SC-005**: Executar a consulta de resolução em tempo inferior a 50 milissegundos por requisição em ambiente local de processamento.
- **SC-006**: Manter 100% de conformidade com o Princípio II e Princípio VIII da Constituição do projeto, operando com zero chamadas externas de rede e zero dependência de CPF.

## Assumptions

- O repositório disponibiliza localmente a base dimensional canônica unificada de parlamentares federais (Câmara, Senado e TSE).
- Os cargos eletivos contemplados no escopo desta funcionalidade restringem-se ao nível federal brasileiro: Deputado Federal e Senador.
- Casos em que o nome do parlamentar não seja encontrado na base canônica levarão o agente de checagem a registrar a alegação como `INCONCLUSIVO` devido à impossibilidade de verificação factual contra dados oficiais.
- A tolerância a variações textuais será calibrada de maneira conservadora para mitigar riscos de falsas atribuições em contexto de checagem eleitoral e política.
