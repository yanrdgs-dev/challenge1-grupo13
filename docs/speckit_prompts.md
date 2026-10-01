Este projeto constrói um agente de fact-checking político brasileiro. As seguintes
regras são inegociáveis para qualquer feature construída neste repositório:

1. Nenhum veredito sem evidência rastreável. O agente nunca responde VERDADEIRO ou
   FALSO a partir da memória do modelo. Todo veredito final precisa
   citar o resultado de uma tool específica e a fonte primária correspondente
   (dataset oficial, API pública ou base normativa curada). Se nenhuma tool
   retornou evidência suficiente, o veredito é INCONCLUSIVO — nunca um palpite.

2. Resolução de entidade é obrigatória antes de qualquer consulta de dado. Nenhuma
   tool de dado ou API pode ser chamada com nome de parlamentar ou proposição em
   texto livre. A entidade precisa primeiro passar por uma tool de resolução
   (nome → ID canonico), para impedir erro por homonimo ou correspondência
   inventada. Join de identidade nunca pode depender de CPF, apenas nome normalizado + UF/cargo.

3. Claims subespecificadas resultam em INCONCLUSIVO, não em parâmetro inventado.
   Se a alegação não nomeia uma entidade resolvível, usa referência temporal
   relativa não ancorável, cita fonte de baixa credibilidade (rede social, boato,
   "comentários na imprensa") ou descreve um evento futuro/ainda não ocorrido, o
   agente deve reconhecer isso antes de chamar qualquer tool e devolver
   INCONCLUSIVO com a justificativa e nunca forçar uma correspondência para gerar
   uma resposta.

4. Separação entre tool de dado transacional e tool de regra institucional. Uma
   claim sobre "o que aconteceu" (valores, votos, ranking) é resolvida por tools
   que consultam dado real. Uma claim sobre "o que é permitido/como funciona"
   (normas, regimentos, procedimentos) é resolvida por uma base de conhecimento
   curada e versionada, nunca inferida silenciosamente a partir do dado
   transacional sem checar a fonte normativa.

5. O golden dataset é o portão de aceite. Nenhuma tool ou fluxo de agente é
   considerado pronto sem passar nas 30 alegações de golden_dataset_v1.json,
   cobrindo os veredictos VERDADEIRO, FALSO e INCONCLUSIVO. Alegações novas
   adicionadas ao dataset exigem cobertura de tool correspondente antes do merge.

6. Neutralidade de veredito. O agente não pode ter viés de confirmação em
   nenhuma direção, nem tendendo a FALSO (mesmo sabendo que agências de
   checagem historicamente publicam mais desmentidos que confirmações), nem
   tendendo a validar a alegação do usuário. A linguagem da resposta final deve
   ser neutra independente do veredito.

7. TDD é obrigatório e não-negociável. Nenhuma tool ou lógica de agente é escrita
   antes do teste que a especifica. Ciclo red-green-refactor: escrever o teste
   unitário falhando, implementar o mínimo para passar, só então refatorar. Pull
   requests que adicionam código sem teste correspondente anterior são rejeitados.

8. Toda tool do catálogo precisa de suíte de teste unitário cobrindo, no mínimo:
   caminho feliz (entidade resolvida, dado encontrado), entidade não encontrada,
   entidade ambígua (quando aplicável) e, para tools que chamam API externa,
   timeout/erro de rede simulado (mock), sem depender de chamada real à API em
   teste unitário. As claims de golden_dataset_v1.json que mapeiam para uma tool
   servem de base para os casos de teste, mas não substituem os testes unitários
   da tool isolada.

9. Commits seguem Conventional Commits (feat:, fix:, test:, docs:, refactor:,
   chore:), com escopo indicando o módulo afetado (ex.: feat(tools): adiciona
   resolve_politician, test(gastos): cobre check_parliamentary_expenses). Commits
   de teste que antecedem a implementação (parte do ciclo TDD) usam test: mesmo
   quando o código ainda não existe.

10. Toda a implementação é em Python: tools, agentes, orquestração e client HTTP.
    Bibliotecas já padronizadas no projeto (Polars/DuckDB para consulta sobre
    Parquet local, conforme docs/data_schemas.md) devem ser reaproveitadas; não
    introduzir stack paralela para a mesma finalidade sem atualizar esta
    constituição.
