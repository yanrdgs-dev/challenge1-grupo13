"""Gestão de prompts via Langfuse, com cache e fallback para o prompt local.

Garantias:
- Tracing desligado ⇒ prompt local, zero chamadas de rede.
- Langfuse fora do ar ⇒ prompt local, sem pagar o timeout em toda request (disjuntor simples).
- Nunca levanta exceção: o prompt local é sempre uma resposta válida.

O prompt local usa a mesma sintaxe ``{{variavel}}`` do Langfuse, então os dois são intercambiáveis.
"""

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.observability import tracing

logger = logging.getLogger("Prompts")

DEFAULT_LABEL = "production"
DEFAULT_CACHE_TTL_SECONDS = 60
FETCH_TIMEOUT_SECONDS = 2
FAILURE_BACKOFF_SECONDS = 30

# nome do prompt -> instante (monotonic) até o qual não se tenta o Langfuse de novo
_failed_until: Dict[str, float] = {}

_VARIABLE_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


@dataclass
class PromptResult:
    text: str
    name: str
    version: Optional[int]
    label: str
    source: str                      # "langfuse" ou "local"
    prompt_client: Any = None        # cliente do Langfuse, para ligar a generation à versão


def compile_template(template: str, variables: Optional[Dict[str, Any]] = None) -> str:
    """Substitui ``{{variavel}}`` numa única passada (valores não são reinterpretados)."""
    variables = variables or {}

    def replace(match: "re.Match[str]") -> str:
        key = match.group(1)
        return str(variables[key]) if key in variables else match.group(0)

    return _VARIABLE_RE.sub(replace, template)


def _get_client() -> Any:
    return tracing._get_client()


def _cache_ttl() -> int:
    try:
        return int(os.getenv("PROMPT_CACHE_TTL_SECONDS", str(DEFAULT_CACHE_TTL_SECONDS)))
    except ValueError:
        return DEFAULT_CACHE_TTL_SECONDS


def _local(name: str, fallback: str, variables: Optional[Dict[str, Any]], label: str) -> PromptResult:
    return PromptResult(
        text=compile_template(fallback, variables), name=name, version=None, label=label, source="local"
    )


def get_prompt(
    name: str,
    fallback: str,
    variables: Optional[Dict[str, Any]] = None,
    label: Optional[str] = None,
) -> PromptResult:
    """Prompt ``name`` do Langfuse (label ``production`` por padrão) ou o ``fallback`` local.

    ``label`` explícito vence ``LANGFUSE_PROMPT_LABEL`` (usado para rodar experiments com ``staging``).
    """
    label = label or os.getenv("LANGFUSE_PROMPT_LABEL") or DEFAULT_LABEL

    if not tracing.is_enabled() or time.monotonic() < _failed_until.get(name, 0.0):
        return _local(name, fallback, variables, label)

    try:
        client_prompt = _get_client().get_prompt(
            name,
            label=label,
            type="text",
            fallback=fallback,
            cache_ttl_seconds=_cache_ttl(),
            max_retries=0,
            fetch_timeout_seconds=FETCH_TIMEOUT_SECONDS,
        )
        if getattr(client_prompt, "is_fallback", False):
            # O SDK não conseguiu buscar e devolveu o fallback: trata como indisponível.
            _failed_until[name] = time.monotonic() + FAILURE_BACKOFF_SECONDS
            return _local(name, fallback, variables, label)
        return PromptResult(
            text=client_prompt.compile(**(variables or {})),
            name=name,
            version=client_prompt.version,
            label=label,
            source="langfuse",
            prompt_client=client_prompt,
        )
    except Exception as exc:
        logger.warning("Prompt '%s' indisponível no Langfuse, usando o local: %s", name, exc)
        _failed_until[name] = time.monotonic() + FAILURE_BACKOFF_SECONDS
        return _local(name, fallback, variables, label)
