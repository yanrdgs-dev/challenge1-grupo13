"""Configuração global dos testes.

Força o tracing do Langfuse desligado ANTES de qualquer import do projeto, para que as chaves
reais do `.env` local nunca enviem traces de teste ao Langfuse Cloud. O python-dotenv não
sobrescreve variáveis que já existem no ambiente.
"""

import os

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"


from contextlib import contextmanager  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402


class SpanRecorder:
    """Registra as observações abertas, com o pai de cada uma, para testar a estrutura do trace."""

    def __init__(self, trace_id=None):
        self.spans = []
        self.trace_id = trace_id
        self._stack = []

    @contextmanager
    def observation(self, name, as_type="span", **kwargs):
        record = {
            "name": name,
            "as_type": as_type,
            "parent": self._stack[-1] if self._stack else None,
            "kwargs": kwargs,
            "updates": [],
        }
        self.spans.append(record)
        self._stack.append(name)

        recorder = self

        class _Handle:
            @property
            def trace_id(self_inner):
                return recorder.trace_id

            def update(self_inner, **update):
                record["updates"].append(update)

        try:
            yield _Handle()
        finally:
            self._stack.pop()

    def tree(self):
        """Lista de (nome, pai) na ordem de abertura."""
        return [(s["name"], s["parent"]) for s in self.spans]

    def get(self, name):
        return next(s for s in self.spans if s["name"] == name)

    def merged_updates(self, name):
        merged = {}
        for update in self.get(name)["updates"]:
            merged.update(update)
        return merged


@pytest.fixture
def trace_recorder():
    recorder = SpanRecorder()
    with patch("src.observability.tracing.observation", recorder.observation):
        yield recorder
