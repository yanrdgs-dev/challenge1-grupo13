"""Os testes nunca usam chaves reais de provedor: um .env preenchido não pode virar chamada paga ou de rede."""

import os

import pytest


@pytest.mark.parametrize("name", ["GROQ_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY"])
def test_provider_keys_are_blank_inside_every_test(name):
    assert os.environ.get(name, "") == ""
