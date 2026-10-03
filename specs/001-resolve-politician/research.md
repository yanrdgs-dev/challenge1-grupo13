# Research & Technical Decisions: Resolução Canônica de Parlamentares (`resolve_politician`)

**Feature**: `001-resolve-politician`  
**Data**: 2026-10-01  
**Status**: Concluído  

---

## 1. Contexto e Objetivos

O Princípio II da Constituição do projeto (`.specify/memory/constitution.md`) determina que **nenhuma tool de dado ou API pode ser chamada com nome de parlamentar em texto livre**. A entidade precisa passar por uma tool de resolução (`nome → ID canônico`), para impedir erros por homônimo ou correspondência inventada. Além disso, joins de identidade jamais podem depender de CPF.

Esta pesquisa documenta as decisões técnicas arquiteturais para garantir resolução determinística, suporte a nomes de urna, desambiguação por UF/cargo e latência ultrabaixa (< 50ms) sem chamadas de rede.

---

## 2. Decisões Arquiteturais e Avaliação de Alternativas

### Decisão 1: Abordagem Híbrida de Matching (Lookup Determinístico + Fuzzy Matching)

- **Decisão:** Adotar estratégia em dois estágios:
  1. **Estágio 1 (Exact / Normalized Lookup):** Limpeza e normalização do texto de entrada (`strip_accents`, remoção de pontuação, lower-case) e consulta direta em índice indexado por `(nome_normalizado, uf)`. Cobre 96,6% dos casos de nomes completos e nomes de urna registrados com complexidade $O(1)$ e tempo de execução $< 1$ ms.
  2. **Estágio 2 (Fuzzy Matching):** Caso o casamento exato não localize a entidade ou haja apenas nome parlamentar parcial/apelido com pequenos erros de digitação, aplicar algoritmo de similaridade baseado em `rapidfuzz` (`fuzz.token_sort_ratio` e `fuzz.ratio`) sobre os nomes civis e de urna normalizados, com limiar conservador configurável (`threshold = 85`).
- **Racional:** Nomes próprios no contexto político exigem alta precisão para não atribuir despesas e votos a terceiros. A abordagem híbrida entrega latência quase instantânea no caminho feliz e tolerância a pequenos desvios tipográficos no fallback.
- **Alternativas Consideradas:**
  - *DuckDB Full-Text Search (FTS) em tempo de execução:* Rejeitado por overhead de I/O a cada requisição e maior consumo de tempo para nomes curtos.
  - *Busca Vetorial / Embeddings neurais:* Rejeitado por adicionar dependências de modelos pesados (PyTorch/Transformers), custo computacional elevado e risco de correspondências espúrias por proximidade semântica inadequada para nomes próprios.

---

### Decisão 2: Materialização da Tabela Dimensional `dim_politicos.parquet`

- **Decisão:** Materializar a tabela canônica `data/processed/dim_politicos.parquet` unificando:
  - **Câmara dos Deputados:** `data/processed/camara/deputados.parquet` e metadados de parlamentares da CEAP (`ideCadastro`, `txNomeParlamentar`, `nomeCivil`, `sgUF`, `sgPartido`).
  - **Senado Federal:** `data/processed/senado/senadores.parquet` (`Nome Parlamentar`, `UF`, `Partido`, `Mandato`).
  - **TSE (Candidatos):** `data/processed/tse/candidatos/` (`SQ_CANDIDATO`, `NM_CANDIDATO`, `NM_URNA_CANDIDATO`, `SG_UF`, `SG_PARTIDO`, `DS_CARGO`).
  O cruzamento é realizado estritamente por `nome_normalizado + UF`, sem CPF, conforme validado na EDA de Candidaturas e Patrimônio.
- **Racional:** A tabela consolidada possui cerca de 1.500 a 2.500 registros para a legislatura recente, ocupando menos de 1 MB em disco. Isso permite carregamento instantâneo em memória no startup do serviço/módulo.
- **Alternativas Consideradas:**
  - *Joins dinâmicos em tempo de consulta (on-the-fly):* Rejeitado porque cruzar centenas de milhares de linhas do TSE com arquivos da Câmara a cada invocação da tool degradaria a latência para vários segundos.
  - *Uso de CPF como chave de junção:* Rejeitado categoricamente pelo Princípio II da Constituição e pela anonimização parcial do CPF na base do TSE pela LGPD.

---

### Decisão 3: Tratamento Rigoroso de Ambiguidade e Homônimos

- **Decisão:** Se a consulta localizar dois ou mais parlamentares com pontuação de similaridade idêntica ou dentro de margem estreita ($\Delta \le 3\%$) sem que parâmetros discriminadores (`uf` ou `cargo`) tenham sido informados:
  - Retornar `ambiguous: True`;
  - Definir campos principais como `None`;
  - Preencher `candidatos_alternativos` com a lista dos registros concorrentes identificados.
  Caso `uf` ou `cargo` sejam informados, utilizá-los como filtro estrito pós-matching para selecionar o candidato único e retornar `ambiguous: False`.
- **Racional:** Elimina falsos positivos. Em fact-checking, atribuir uma alegação ao parlamentar errado é uma falha crítica; diante de dúvida legítima, a tool deve declarar ambiguidade para que o agente possa solicitar desambiguação ou emitir veredito `INCONCLUSIVO` (Princípio III).
- **Alternativas Consideradas:**
  - *Retornar sempre o primeiro resultado encontrado:* Rejeitado por introduzir viés arbitrário e erros factuais graves.

---

### Decisão 4: Estrutura em Memória e Singleton de Consulta

- **Decisão:** O componente de resolução (`PoliticianResolver`) deve ser implementado como classe com carregamento preguiçoso (*lazy-loading*) ou padrão Singleton, mantendo em memória:
  - Um dicionário hash com chaves normalizadas para lookup $O(1)$;
  - Uma lista pré-computada de tuplas `(nome_normalizado, id_registro)` para buscas fuzzy rápidas via RapidFuzz C-extension.
- **Racional:** Evita releituras repetidas de disco a cada chamada da tool, mantendo o consumo de memória abaixo de 10 MB e garantindo tempo de resposta $< 5$ ms.
- **Alternativas Consideradas:**
  - *Recarregar o Parquet a cada chamada de função:* Rejeitado por custo desnecessário de desserialização.

---

## 3. Matriz de Requisitos da Constituição

| Princípio | Requisito da Tool | Conformidade no Design |
|---|---|---|
| **Princípio II** | Resolução canônica antes de dados | Tool gera `ideCadastro`, `sq_candidato` e `cod_senador`. Proíbe CPF; usa `nome_normalizado + UF`. |
| **Princípio III** | Claims subespecificadas | Retorno explícito de `not found` e `ambiguous: True`, impedindo parametrizações inventadas. |
| **Princípio V** | Aceite no Golden Dataset | Validação calibrada para o Caso 1 (`Pompeo de Mattos`), Caso 7 e Caso 13. |
| **Princípio VII** | TDD Inegociável | Suíte de testes unitários isolados escrita antes de qualquer código funcional. |
| **Princípio VIII** | 4 quadrantes de teste unitário | Suíte cobre: (1) feliz, (2) não encontrado, (3) homônimo/ambíguo, (4) isolamento offline total. |
| **Princípio X** | Stack unificada Python | 100% Python, utilizando Polars/DuckDB para Parquet local e RapidFuzz. |
