# Quickstart & Guia de Validação: `resolve_proposition`

**Feature**: `002-resolve-proposition`  
**Data**: 2026-10-01  
**Status**: Concluído  

---

## 1. Pré-Requisitos

1. **Ambiente Python**:
   - Python 3.11+ no ambiente virtual `.venv`.
   - Pacotes essenciais instalados: `httpx>=0.27.0`, `rapidfuzz>=3.0.0`, `pytest>=8.0.0`, `pytest-mock>=3.14.0`.
2. **Conectividade Externa (ou Mocks)**:
   - Para execução em produção: acesso aos portais de Dados Abertos da Câmara e do Senado.
   - Para execução em testes unitários: 100% isolado via mocks sem chamadas de rede (Princípio VIII).

---

## 2. Cenários de Validação Ponta a Ponta

### Cenário 1: Resolução Exata do "PL das Fake News" (PL 2630/2020 - Claim 4 do Golden Dataset)
- **Objetivo:** Resolver matéria identificada por tipo, número e ano na Câmara dos Deputados.
- **Invocação:**
  ```python
  from src.tools.resolve_proposition import resolve_proposition

  result = resolve_proposition(casa="camara", sigla_tipo="PL", numero=2630, ano=2020)
  print(result)
  ```
- **Resultado Esperado:**
  - `ambiguous`: `False`
  - `id_proposicao`: `2253965` (ID oficial na Câmara)
  - `sigla_tipo`: `"PL"`
  - `numero`: `2630`
  - `ano`: `2020`
  - `ementa`: Contém texto sobre liberdade, responsabilidade e transparência na internet.
  - `candidatos`: `[]`

---

### Cenário 2: Resolução da PEC da Reforma Tributária no Senado (PEC 45/2019 - Claim 5 do Golden Dataset)
- **Objetivo:** Resolver proposição formal do Senado Federal.
- **Invocação:**
  ```python
  result = resolve_proposition(casa="senado", sigla_tipo="PEC", numero=45, ano=2019)
  ```
- **Resultado Esperado:**
  - `ambiguous`: `False`
  - `casa`: `"senado"`
  - `ementa`: Contém texto oficial sobre alteração do Sistema Tributário Nacional.
  - `candidatos`: `[]`

---

### Cenário 3: Resolução por Nome Popular ("Marco Temporal" - Claim 15 do Golden Dataset)
- **Objetivo:** Resolver projeto através de nome popular na Câmara em 2023.
- **Invocação:**
  ```python
  result = resolve_proposition(casa="camara", termo_busca="Marco Temporal", ano=2023)
  ```
- **Resultado Esperado:**
  - `ambiguous`: `False`
  - `id_proposicao`: Resolvido para a matéria correspondente (PL 490/2007 ou PL 2903/2023).
  - `match_score`: $\ge 80.0$

---

### Cenário 4: Detecção de Ambiguidade em Tema Genérico (Claim 26 do Golden Dataset)
- **Objetivo:** Garantir que buscas genéricas sem número formal sinalizem ambiguidade para apoiar veredito `INCONCLUSIVO`.
- **Invocação:**
  ```python
  result = resolve_proposition(casa="senado", termo_busca="segurança pública")
  ```
- **Resultado Esperado:**
  - `ambiguous`: `True`
  - `id_proposicao`: `None`
  - `candidatos`: Lista não vazia contendo os múltiplos projetos de segurança pública identificados.

---

### Cenário 5: Proposição Inexistente
- **Objetivo:** Verificar retorno estruturado sem correspondências espúrias.
- **Invocação:**
  ```python
  result = resolve_proposition(casa="camara", sigla_tipo="PL", numero=999999, ano=2020)
  ```
- **Resultado Esperado:**
  - `ambiguous`: `False`
  - `id_proposicao`: `None`
  - `ementa`: `None`
  - `candidatos`: `[]`

---

## 3. Execução da Suíte de Testes com Mocks (Princípio VIII)

Para verificar o comportamento da tool sem efetuar chamadas reais de rede e simulando timeouts/erros:

```bash
.venv/bin/pytest tests/test_resolve_proposition.py -v
```
