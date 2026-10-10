"""Validação e normalização dos parâmetros de tool contra o schema do catálogo.

O LLM de roteamento omite parâmetros obrigatórios, escreve ``"Câmara"`` em vez de ``camara`` ou envia
``"2023"`` como texto. Aqui tudo isso é corrigido quando seguro, ou recusado com uma mensagem clara,
antes de a tool rodar.
"""

import re
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


# --------------------------- ancoragem dos filtros de candidato --------------------------- #

CANDIDATE_TOOLS = frozenset({
    "resolve_candidate", "get_candidate_votes", "check_candidate_status", "check_disqualification_motive",
    "check_candidate_profile", "get_candidate_assets", "check_cash_and_special_assets",
    "verify_official_social_media", "get_campaign_finances",
})

_CARGO_PATTERNS = {
    "Presidente": r"presiden",
    "Governador": r"governador|governadora",
    "Senador": r"senador|senadora",
    "Deputado Federal": r"deputad[oa]s?\s+federa",
    "Deputado Estadual": r"deputad[oa]s?\s+estadua",
    "Deputado Distrital": r"deputad[oa]s?\s+distrita",
}
_STATES = {
    "AC": "acre", "AL": "alagoas", "AP": "amapa", "AM": "amazonas", "BA": "bahia", "CE": "ceara",
    "DF": "distrito federal", "ES": "espirito santo", "GO": "goias", "MA": "maranhao", "MT": "mato grosso",
    "MS": "mato grosso do sul", "MG": "minas gerais", "PA": "para", "PB": "paraiba", "PR": "parana",
    "PE": "pernambuco", "PI": "piaui", "RJ": "rio de janeiro", "RN": "rio grande do norte",
    "RS": "rio grande do sul", "RO": "rondonia", "RR": "roraima", "SC": "santa catarina", "SP": "sao paulo",
    "SE": "sergipe", "TO": "tocantins",
}
_STATE_NAMES_LONGEST_FIRST = sorted(_STATES.items(), key=lambda item: -len(item[1]))


def _states_mentioned(claim: str) -> set:
    """UFs que a claim escreve: pela sigla em maiúsculas ("PL-SP") ou pelo nome ("São Paulo")."""
    found = {m.group(0) for m in re.finditer(r"(?<![A-Za-z])[A-Z]{2}(?![A-Za-z])", claim) if m.group(0) in _STATES}
    folded = _fold(claim)
    for uf, name in _STATE_NAMES_LONGEST_FIRST:
        if uf == "PA" and "pará" not in claim.lower():
            continue  # "para" é preposição: só vale o estado escrito com acento
        pattern = rf"(?<![a-z]){re.escape(name)}(?![a-z])"
        if re.search(pattern, folded):
            found.add(uf)
            folded = re.sub(pattern, " ", folded)  # "Mato Grosso do Sul" não conta também como "Mato Grosso"
    return found


def ground_candidate_args(tool_name: str, args: Any, claim_text: str) -> Any:
    """Descarta ``cargo``, ``uf`` e ``numero`` de candidato que o LLM preencheu e que a claim não diz.

    Com o filtro errado a tool resolve outra candidatura (ex.: o "Pablo Marçal" de Deputado Federal no lugar do
    de Presidente) e o veredito sai sobre a pessoa errada. Sem o filtro, o homônimo volta a ser ambíguo.
    Não altera a entrada e só atua nas tools que resolvem candidato.
    """
    if tool_name not in CANDIDATE_TOOLS or not isinstance(args, dict):
        return args
    grounded = dict(args)
    text = claim_text or ""
    folded = _fold(text)

    cargo = grounded.get("cargo")
    if cargo and not re.search(_CARGO_PATTERNS.get(str(cargo), r"(?!)"), folded):
        grounded.pop("cargo")
    uf = grounded.get("uf")
    if uf and str(uf).strip().upper() not in _states_mentioned(text):
        grounded.pop("uf")
    numero = grounded.get("numero")
    if numero is not None and not re.search(rf"(?<!\d){re.escape(str(numero))}(?!\d)", text):
        grounded.pop("numero")
    return grounded
