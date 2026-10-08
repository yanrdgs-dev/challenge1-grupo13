"""Configuração global dos testes.

Força o tracing do Langfuse desligado ANTES de qualquer import do projeto, para que as chaves
reais do `.env` local nunca enviem traces de teste ao Langfuse Cloud. O python-dotenv não
sobrescreve variáveis que já existem no ambiente.
"""

import os

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
