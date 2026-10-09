"""Validação e normalização dos parâmetros de tool contra o schema do catálogo.

O LLM de roteamento omite parâmetros obrigatórios, escreve ``"Câmara"`` em vez de ``camara`` ou envia
``"2023"`` como texto. Aqui tudo isso é corrigido quando seguro, ou recusado com uma mensagem clara,
antes de a tool rodar.
"""

import unicodedata
from typing import Any, Dict, Optional, Tuple

from src.services.tool_catalog import TOOLS_CATALOG

_TRUE = {"true", "sim", "1"}
_FALSE = {"false", "nao", "não", "0"}


def _fold(text: str) -> str:
    """Minúsculas e sem acentos, para comparar enums."""
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _schema(tool_name: str) -> Optional[Dict[str, Any]]:
    for tool in TOOLS_CATALOG:
        if tool["function"]["name"] == tool_name:
            return tool["function"]["parameters"]
    return None


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _coerce(name: str, value: Any, spec: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    kind = spec.get("type")
    enum = spec.get("enum")

    if enum and isinstance(value, str):
        folded = {_fold(option): option for option in enum}
        match = folded.get(_fold(value))
        if match is None:
            return value, f"Valor inválido para '{name}': {value!r}. Valores permitidos: {', '.join(enum)}."
        return match, None

    if kind == "integer":
        if isinstance(value, bool):
            return value, f"'{name}' deve ser um número inteiro, recebido {value!r}."
        if isinstance(value, int):
            return value, None
        if isinstance(value, float) and value.is_integer():
            return int(value), None
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip()), None
        return value, f"'{name}' deve ser um número inteiro, recebido {value!r}."

    if kind == "boolean":
        if isinstance(value, bool):
            return value, None
        if isinstance(value, str) and _fold(value) in _TRUE:
            return True, None
        if isinstance(value, str) and _fold(value) in _FALSE:
            return False, None
        return value, f"'{name}' deve ser verdadeiro ou falso, recebido {value!r}."

    return value, None


def validate_tool_args(tool_name: str, args: Any) -> Tuple[Any, Optional[str]]:
    """Devolve ``(argumentos_normalizados, None)`` ou ``(argumentos, mensagem_de_erro)``.

    Tool fora do catálogo passa sem validação (quem trata é o despachante). A entrada não é alterada.
    """
    schema = _schema(tool_name)
    if schema is None:
        return args, None
    if not isinstance(args, dict):
        return args, f"Os parâmetros da tool '{tool_name}' devem ser um objeto, recebido {type(args).__name__}."

    properties = schema.get("properties", {})
    normalized = dict(args)

    missing = [name for name in schema.get("required", []) if _is_blank(normalized.get(name))]
    if missing:
        return args, f"Parâmetros obrigatórios ausentes para '{tool_name}': {', '.join(missing)}."

    for name, value in list(normalized.items()):
        spec = properties.get(name)
        if spec is None or _is_blank(value):
            continue
        coerced, problem = _coerce(name, value, spec)
        if problem:
            return args, problem
        normalized[name] = coerced
    return normalized, None
