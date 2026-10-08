# Etapa 7 — Interface Gráfica

## Objetivo

Fornecer uma interface web interativa para uso em demonstrações ao vivo, permitindo que o usuário insira uma alegação política e visualize o veredito com suas fontes e explicação.

**Issues:** [#20 — 3.3 Interface Gráfica](https://github.com/yanrdgs-dev/challenge1-grupo13/issues/20) | [#31 — 4.5 Suporte a Links de Notícias](https://github.com/yanrdgs-dev/challenge1-grupo13/issues/31)

!!! note "Branch de trabalho"
    A interface está implementada na branch [`integracao-interface-agentes`](https://github.com/yanrdgs-dev/challenge1-grupo13/tree/integracao-interface-agentes), no diretório `frontend/`.

---

## Stack tecnológica

| Tecnologia | Versão | Função |
|---|---|---|
| **React** | 18+ | Framework de UI |
| **TypeScript** | 5+ | Tipagem estática |
| **Vite** | 5+ | Bundler e dev server |
| **CSS Modules** | — | Estilização por componente |

---

## Executar a interface

```bash
# Entrar no diretório da interface (branch integracao-interface-agentes)
cd frontend/

# Instalar dependências Node
npm install

# Subir dev server
npm run dev
# Interface disponível em: http://localhost:5173
```

!!! warning "Pré-requisito"
    O Router Service deve estar em execução em `http://localhost:8000` para que a interface se comunique com o backend.

---

## Funcionalidades implementadas

=== "Checagem Manual"

    - Campo de texto para inserir a alegação diretamente.
    - Botão para enviar e aguardar o veredito.
    - Exibição do resultado com badge colorido:
        - 🟢 **VERDADEIRO**
        - 🔴 **FALSO**
        - 🟡 **INCONCLUSIVO**
    - Painel com explicação detalhada e fontes primárias.

=== "Histórico de Chats"

    - Histórico dinâmico das checagens realizadas na sessão.
    - Permite revisitar resultados anteriores sem reenviar a claim.

---

## Próximas features planejadas (Issues abertas)

| Issue | Feature | Status |
|---|---|---|
| [#31](https://github.com/yanrdgs-dev/challenge1-grupo13/issues/31) | Aba "Checar por Link de Notícia" com renderização de metadados | 🔜 Pendente |
| [#30](https://github.com/yanrdgs-dev/challenge1-grupo13/issues/30) | Exibição do veredito consolidado de matérias completas | 🔜 Pendente |
