"""Wrapper de tracing sobre o SDK do Langfuse.

Garantias:
- Desligado (``LANGFUSE_TRACING_ENABLED=false`` ou sem chaves) vira no-op: zero chamadas de rede.
- Nenhuma falha do Langfuse derruba a request: toda chamada ao SDK é protegida.
- Exceções do corpo do ``with`` sempre se propagam normalmente.
"""

import logging
import os
import re
import sys
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("Tracing")


def is_enabled() -> bool:
    """Tracing ativo apenas se não foi desligado e as duas chaves existem."""
    if os.getenv("LANGFUSE_TRACING_ENABLED", "true").strip().lower() == "false":
        return False
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


# W3C Trace Context: versão-trace_id(32 hex)-span_id(16 hex)-flags. Hexadecimal minúsculo.
_TRACEPARENT_RE = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


def parse_traceparent(value: Optional[str]) -> Optional[Dict[str, str]]:
    """Converte um header ``traceparent`` em ``TraceContext`` do Langfuse; None se inválido."""
    if not value:
        return None
    match = _TRACEPARENT_RE.match(value.strip())
    if not match:
        return None
    version, trace_id, span_id, _flags = match.groups()
    if version == "ff" or set(trace_id) == {"0"} or set(span_id) == {"0"}:
        return None
    return {"trace_id": trace_id, "parent_span_id": span_id}


def traceparent_header() -> Dict[str, str]:
    """Header ``traceparent`` do span atual, para propagar o trace a outro serviço.

    Devolve ``{}`` se o tracing estiver desligado, não houver span ativo ou o SDK falhar.
    """
    if not is_enabled():
        return {}
    try:
        client = _get_client()
        trace_id = client.get_current_trace_id()
        span_id = client.get_current_observation_id()
    except Exception as exc:
        logger.warning("Falha ao montar traceparent: %s", exc)
        return {}
    if not trace_id or not span_id:
        return {}
    return {"traceparent": f"00-{trace_id}-{span_id}-01"}


def release() -> Optional[str]:
    """Versão da aplicação: ``GIT_SHA`` (injetado no build) ou ``LANGFUSE_RELEASE``."""
    return os.getenv("GIT_SHA") or os.getenv("LANGFUSE_RELEASE") or None


def _get_client() -> Any:
    from langfuse import get_client

    # O SDK só conhece LANGFUSE_RELEASE; mapeia o GIT_SHA do build antes de criar o client.
    git_sha = os.getenv("GIT_SHA")
    if git_sha and not os.getenv("LANGFUSE_RELEASE"):
        os.environ["LANGFUSE_RELEASE"] = git_sha
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


    def score_trace(self, **kwargs: Any) -> None:
        """Registra um score no trace (ex.: veredito categórico). Nunca levanta."""
        if self._obs is None:
            return
        try:
            self._obs.score_trace(**kwargs)
        except Exception as exc:
            logger.warning("Falha ao registrar score no Langfuse: %s", exc)


@contextmanager
def observation(
    name: str,
    as_type: str = "span",
    traceparent: Optional[str] = None,
    **kwargs: Any,
) -> Iterator[_Handle]:
    """Abre um span/generation/etc. como contexto atual; no-op se o tracing estiver desligado.

    Com ``traceparent`` válido, continua o trace de outro serviço (o span fica sob o span remoto).
    """
    cm = None
    handle = _Handle()
    if is_enabled():
        trace_context = parse_traceparent(traceparent)
        if trace_context:
            kwargs["trace_context"] = trace_context
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


# Limite do Langfuse: ids de usuário e sessão acima de 200 caracteres são descartados.
_MAX_ID_LENGTH = 200


def _clean_id(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= _MAX_ID_LENGTH else None


def _propagate_attributes(**kwargs: Any) -> Any:
    from langfuse import propagate_attributes

    return propagate_attributes(**kwargs)


@contextmanager
def trace_attributes(
    user_id: Optional[str] = None, session_id: Optional[str] = None
) -> Iterator[None]:
    """Associa ``user_id`` e ``session_id`` a todos os spans criados dentro do contexto.

    Ambos são opcionais: sem eles (usuário deslogado), ou com tracing desligado, não faz nada.
    Deve envolver a criação do span raiz.
    """
    attrs = {
        key: cleaned
        for key, cleaned in (("user_id", _clean_id(user_id)), ("session_id", _clean_id(session_id)))
        if cleaned
    }
    cm = None
    if attrs and is_enabled():
        try:
            cm = _propagate_attributes(**attrs)
            cm.__enter__()
        except Exception as exc:
            logger.warning("Falha ao propagar user_id/session_id no Langfuse: %s", exc)
            cm = None

    try:
        yield
    except BaseException:
        _safe_exit(cm, "trace_attributes", *sys.exc_info())
        raise
    else:
        _safe_exit(cm, "trace_attributes", None, None, None)


def score_trace_by_id(trace_id: str, name: str, value: str, comment: Optional[str] = None) -> bool:
    """Registra um score categórico num trace já existente (ex.: feedback do usuário). Nunca levanta.

    Devolve True quando o score foi enviado ao Langfuse; False com o tracing desligado ou em erro.
    """
    if not is_enabled() or not trace_id:
        return False
    try:
        _get_client().create_score(
            name=name, value=value, trace_id=trace_id, data_type="CATEGORICAL", comment=comment
        )
        return True
    except Exception as exc:
        logger.warning("Falha ao registrar score por trace_id no Langfuse: %s", exc)
        return False


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
