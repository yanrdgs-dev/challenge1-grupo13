# Implementation Plan: Resolução Canônica de Proposições (`resolve_proposition`)

**Branch**: `002-resolve-proposition` | **Date**: 2026-10-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-resolve-proposition/spec.md`

## Summary

Implementação da tool canônica de identificação e resolução de proposições e matérias legislativas (`resolve_proposition`) para a Câmara dos Deputados, Senado Federal e Congresso Nacional. A ferramenta atende ao Princípio II da Constituição (resolução prévia obrigatória de matérias legislativas antes de consultas de votações nominais) e ao Princípio III (sinalização de `ambiguous: True` para alegações subespecificadas). A solução emprega um cliente HTTP assíncrono/síncrono com `httpx`, timeout estrito de 5 segundos, cache de sessão em memória e fallback com RapidFuzz para buscas temáticas em ementas, além de isolamento 100% mockado nos testes unitários conforme o Princípio VIII.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `httpx>=0.27.0`, `rapidfuzz>=3.0.0`

**Storage**: Cache transitório de sessão em memória (`dict` / `lru_cache`) para evitar requisições redundantes durante a verificação de uma claim.

**Testing**: `pytest>=8.0.0`, `pytest-mock>=3.14.0` (execução 100% offline via mocks dos endpoints HTTP).

**Target Platform**: Execução local no pipeline do agente de fact-checking.

**Project Type**: Módulo Python de Tool do Catálogo do Agente (`src/tools/`).

**Performance Goals**: Latência inferior a 2 segundos em chamadas à API de Dados Abertos e inferior a 5 milissegundos para consultas em cache de sessão ou testes mockados.

**Constraints**:
- Timeout máximo de 5.0 segundos por requisição HTTP externa.
- Degradação graciosa em caso de falha de rede ou timeout (retorno estruturado de erro sem derrubar o pipeline).
- Zero requisições reais de rede na suíte de testes unitários (Princípio VIII).
- Detecção obrigatória de ambiguidade em termos genéricos para alimentar o veredito `INCONCLUSIVO` do Agente Roteador (Princípio III).

**Scale/Scope**: Proposições legislativas federais da Câmara dos Deputados, Senado Federal e matérias conjuntas do Congresso Nacional (PL, PEC, MPV, PDL, etc.).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Princípio Constitucional | Status | Avaliação Técnica & Racional |
|---|---|---|
| **I. Veredito Rastreável** | PASS | Retorna `id_proposicao`, ementa oficial e dados cadastrais diretamente rastreáveis aos portais abertos da Câmara e Senado. |
| **II. Resolução Canônica Obrigatória** | PASS | A feature é mandatória para impedir que tools subsequentes de votações nominais sejam invocadas com texto livre de projetos. |
| **III. Claims Subespecificadas** | PASS | Em caso de termos genéricos (Claims 26 e 30), retorna `ambiguous: True` com a lista de candidatos, instruindo o agente a devolver `INCONCLUSIVO`. |
| **IV. Separação de Dados e Normas** | PASS | Tool estritamente focada na identificação da matéria legislativa; não infere legalidade regimental. |
| **V. Golden Dataset como Portão** | PASS | Cobre e viabiliza a esteira de checagem das claims 4, 5, 15, 18, 26, 28 e 30 de `golden_dataset_v1.json`. |
| **VI. Neutralidade de Veredito** | PASS | Busca objetiva e neutra em dados abertos oficiais, agnóstica a posicionamentos partidários. |
| **VII. TDD Inegociável** | PASS | Suíte unitária `tests/test_resolve_proposition.py` implementada na etapa Red antes da codificação funcional da tool. |
| **VIII. Isolamento e Cobertura de Tools** | PASS | Cobertura dos 4 quadrantes incluindo simulação estrita de timeout (`httpx.ConnectTimeout`) e falha de rede via mocks sem dependência de rede externa. |
| **IX. Commits Convencionais** | PASS | Padrão `test(tools): ...` antecedendo `feat(tools): ...`. |
| **X. Stack Unificada Python** | PASS | Utilização do cliente HTTP já padronizado (`httpx`) e bibliotecas Python do projeto. |

## Project Structure

### Documentation (this feature)

```text
specs/002-resolve-proposition/
├── spec.md              # Especificação formal da feature
├── checklists/
│   └── requirements.md  # Checklist de validação de requisitos
├── plan.md              # Este plano de implementação (/speckit-plan)
├── research.md          # Fase 0: Decisões técnicas de integração e APIs
├── data-model.md        # Fase 1: Entidades, diagramas e transições
├── quickstart.md        # Fase 1: Guia prático de validação e cenários
└── contracts/
    └── resolve_proposition.json # Fase 1: Contrato JSON Schema da tool
```

### Source Code (repository root)

```text
src/
├── tools/
│   ├── __init__.py               # Exporta resolve_proposition
│   ├── resolve_proposition.py    # Lógica de resolução, busca exata e matching de ementa
│   ├── legislative_client.py     # Cliente HTTP especializado para APIs da Câmara e Senado
│   └── normalizer.py             # Normalização de siglas e termos de busca

tests/
└── test_resolve_proposition.py   # Suíte de testes unitários com mocks dos 4 quadrantes
```

**Structure Decision**: Criação do módulo auxiliar `legislative_client.py` em `src/tools/` para encapsular requisições HTTP, cabeçalhos, tratamento de timeouts e cache de sessão, mantendo `resolve_proposition.py` focado nas regras de negócio, desambiguação e contratos.

## Complexity Tracking

| Violação | Justificativa | Alternativa Mais Simples Rejeitada Por Que |
|---|---|---|
| Nenhuma | N/A - Arquitetura estritamente alinhada aos princípios da Constituição e às decisões do time em `docs/tools_specification.md`. | N/A |
