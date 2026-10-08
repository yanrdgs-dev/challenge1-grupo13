"""Wrapper de tracing sobre o SDK do Langfuse.

Garantias:
- Desligado (``LANGFUSE_TRACING_ENABLED=false`` ou sem chaves) vira no-op: zero chamadas de rede.
- Nenhuma falha do Langfuse derruba a request: toda chamada ao SDK é protegida.
- Exceções do corpo do ``with`` sempre se propagam normalmente.
"""

import logging
import os
import sys
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("Tracing")


def is_enabled() -> bool:
    """Tracing ativo apenas se não foi desligado e as duas chaves existem."""
    if os.getenv("LANGFUSE_TRACING_ENABLED", "true").strip().lower() == "false":
        return False
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def _get_client() -> Any:
    from langfuse import get_client

    return get_client()


class _Handle:
    """Observação do Langfuse com ``update`` seguro; sem observação, é um no-op."""

    def __init__(self, obs: Any = None):
        self._obs = obs

    @property
    def trace_id(self) -> Optional[str]:
        return getattr(self._obs, "trace_id", None) if self._obs is not None else None

    def update(self, **kwargs: Any) -> None:
        if self._obs is None:
            return
        try:
            self._obs.update(**kwargs)
        except Exception as exc:
            logger.warning("Falha ao atualizar observação do Langfuse: %s", exc)


@contextmanager
def observation(name: str, as_type: str = "span", **kwargs: Any) -> Iterator[_Handle]:
    """Abre um span/generation/etc. como contexto atual; no-op se o tracing estiver desligado."""
    cm = None
    handle = _Handle()
    if is_enabled():
        try:
            cm = _get_client().start_as_current_observation(name=name, as_type=as_type, **kwargs)
            handle = _Handle(cm.__enter__())
        except Exception as exc:
            logger.warning("Falha ao abrir observação '%s' no Langfuse: %s", name, exc)
            cm = None

    try:
        yield handle
    except BaseException:
        _safe_exit(cm, name, *sys.exc_info())
        raise
    else:
        _safe_exit(cm, name, None, None, None)


def _safe_exit(cm: Any, name: str, exc_type: Any, exc: Any, tb: Any) -> None:
    if cm is None:
        return
    try:
        cm.__exit__(exc_type, exc, tb)
    except Exception as err:
        logger.warning("Falha ao fechar observação '%s' no Langfuse: %s", name, err)


def current_trace_id() -> Optional[str]:
    """ID do trace atual, ou None se o tracing estiver desligado ou falhar."""
    if not is_enabled():
        return None
    try:
        return _get_client().get_current_trace_id()
    except Exception as exc:
        logger.warning("Falha ao obter trace_id: %s", exc)
        return None


def flush() -> None:
    """Envia os eventos pendentes (use no encerramento do processo)."""
    if not is_enabled():
        return
    try:
        _get_client().flush()
    except Exception as exc:
        logger.warning("Falha no flush do Langfuse: %s", exc)


def shutdown() -> None:
    """Encerra o cliente do Langfuse, enviando o que estiver pendente."""
    if not is_enabled():
        return
    try:
        _get_client().shutdown()
    except Exception as exc:
        logger.warning("Falha no shutdown do Langfuse: %s", exc)
