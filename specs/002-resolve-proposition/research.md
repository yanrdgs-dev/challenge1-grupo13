# Research & Technical Decisions: Resolução Canônica de Proposições (`resolve_proposition`)

**Feature**: `002-resolve-proposition`  
**Data**: 2026-10-01  
**Status**: Concluído  

---

## 1. Contexto e Objetivos

O Princípio II da Constituição do projeto determina que **nenhuma tool de dado ou API pode ser chamada com proposição em texto livre**. A matéria precisa passar previamente por uma tool de resolução (`texto → ID canônico`), garantindo identificação inequívoca da proposição legislativa antes da auditoria de votações nominais e tramitações.

Além disso, o Princípio III estabelece que **claims subespecificadas resultam em INCONCLUSIVO**, exigindo que buscas textuais vagas ou genéricas (ex.: Claims 26 e 30 do Golden Dataset) retornem `ambiguous: True` e uma lista de candidatos concorrentes, para que o Agente Roteador decida pelo veredito `INCONCLUSIVO` sem forçar correspondências espúrias.

Por fim, o Princípio VIII exige que ferramentas integradas a APIs externas possuam suíte de testes unitários com simulação de **timeout e falhas de rede mockadas**, sem qualquer dependência de rede em ambiente de teste.

---

## 2. Decisões Arquiteturais e Avaliação de Alternativas

### Decisão 1: Arquitetura de Integração com APIs Públicas da Câmara e do Senado

- **Decisão:** Utilizar o cliente HTTP `httpx` para consultar os endpoints REST oficiais de Dados Abertos:
  1. **Câmara dos Deputados (`dadosabertos.camara.leg.br/api/v2/proposicoes`):**
     - Busca exata: parâmetros `siglaTipo`, `numero`, `ano`, `ordem=DESC`, `ordenarPor=id`.
     - Busca textual/por tema: parâmetro `keywords` (ou termos na query) com refinamento local via similaridade na ementa.
  2. **Senado Federal (`legis.senado.leg.br/dadosabertos/materia/pesquisa/lista`):**
     - Cabeçalho `Accept: application/json`.
     - Parâmetros: `sigla`, `numero`, `ano` ou `palavra`.
  3. **Congresso Nacional (`"congresso"`):**
     - Proposições conjuntas (vetos, créditos orçamentários, mistas) consultadas via endpoint do Senado / Congresso com prefixo de comissão mista ou busca consolidada.
- **Racional:** Os dados de proposições e matérias sofrem atualizações diárias e possuem grande dinamismo na tramitação. As APIs abertas da Câmara e Senado são endpoints estáveis, públicos e sem necessidade de chave de autenticação (API Key), com suporte nativo a JSON.
- **Alternativas Consideradas:**
  - *Ingestão diária de todas as proposições em Parquet local:* Rejeitado pela decisão do time em `tools_specification.md` (eixo de matérias e votações definido para consulta em API com cache temporário em memória).
  - *Web Scraping em HTML do portal das casas:* Rejeitado por fragilidade e violação de boas práticas de consumo de APIs públicas estruturadas.

---

### Decisão 2: Política de Timeout Curto e Cache de Sessão em Memória

- **Decisão:** Configurar timeout estrito de **5.0 segundos** para conexões e leituras HTTP via `httpx.Timeout(5.0)`. Implementar um cache LRU em memória por chave normalizada `(casa, sigla_tipo, numero, ano, termo_busca)` com TTL válido durante a sessão da claim.
- **Racional:** Evita que instabilidades nos portais governamentais travem a esteira do agente de fact-checking. O cache de sessão garante que, se múltiplos nós do agente consultarem a mesma proposição durante a mesma claim (ex.: Roteador e depois Sintetizador), a resposta seja instantânea (< 1ms).
- **Alternativas Consideradas:**
  - *Cache persistente em Redis ou SQLite:* Rejeitado por adicionar infraestrutura desnecessária para uma tool stateless; cache em memória Python (`functools.lru_cache` ou dict com chave hash) é suficiente.

---

### Decisão 3: Mecanismo de Matching Híbrido e Detecção de Ambiguidade

- **Decisão:** 
  1. **Modo Identificador Formal (`sigla_tipo` + `numero` + `ano`):** Se os 3 parâmetros forem informados, efetua busca exata via query params nativos da API. Se retornar exatamente 1 registro, devolve `ambiguous: False` e o `id_proposicao` canônico.
  2. **Modo Busca Textual / Nome Popular (`termo_busca`):** Envia a busca textual para a API da casa legislativa, normaliza as ementas retornadas e calcula similaridade com `rapidfuzz` (`fuzz.token_set_ratio`).
     - Se o melhor candidato tiver score $\ge 80$ e o segundo melhor tiver score inferior por uma margem $\Delta \ge 10\%$, resolve para o líder com `ambiguous: False`.
     - Se múltiplos candidatos tiverem score próximo ($\Delta < 10\%$) ou se a consulta retornar dezenas de itens sem liderança clara (termos vagos como "segurança pública" ou "área fiscal"), retorna `ambiguous: True`, `id_proposicao: None` e popula a lista `candidatos`.
- **Racional:** Atende com precisão ao Princípio III da Constituição, gerando a evidência de ambiguidade que o Agente Roteador necessita para carimbar vereditos `INCONCLUSIVO` sem forçar correspondências.

---

### Decisão 4: Estratégia de Isolamento e Mocking de Testes (Princípio VIII)

- **Decisão:** A suíte de testes unitários utilizará `pytest-mock` e mocks de transporte do `httpx` (`httpx.MockTransport` ou monkeypatching do método `get`).
- **Racional:** Cumpre o mandamento pétreo do Princípio VIII: nenhum teste unitário pode realizar requisições reais de rede. As respostas da API da Câmara e do Senado serão simuladas com payloads JSON reais de amostra, incluindo casos de timeout simulado (`httpx.ConnectTimeout`) e erros 404/500.

---

## 3. Matriz de Requisitos da Constituição

| Princípio | Requisito da Tool | Solução Técnica Adotada |
|---|---|---|
| **Princípio I** | Veredito rastreável | Retorno de `id_proposicao`, ementa oficial e dados cadastrais originados de fontes primárias abertas. |
| **Princípio II** | Resolução canônica antes de dados | Tool gera ID canônico oficial exigido antes de invocar tools de votações nominais. |
| **Princípio III** | Claims subespecificadas | Retorno obrigatório de `ambiguous: True` com array `candidatos` para temas vagos (Claims 26 e 30). |
| **Princípio VIII** | Testes com mock e timeout | Suíte unitária simula timeout, erro 500, não encontrado, ambíguo e feliz 100% offline. |
| **Princípio X** | Stack unificada Python | Cliente baseado em `httpx` e `rapidfuzz`, sem ferramentas paralelas. |
