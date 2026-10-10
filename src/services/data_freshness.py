"""Data da base de dados consultada, para o veredito citar (regra 1: evidência rastreável).

Como a fonte em `sources.py`, a data vem de forma determinística: da tool que de fato executou e do
`ingestion_info.json` que a ingestão publica junto dos parquets, nunca do texto gerado pelo LLM. Só tools que
leem parquet ingerido têm data; as que consultam a API ao vivo ou a base normativa curada não têm.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.services.sources import evidence_failed

INFO_FILE = "ingestion_info.json"
# Brasil não tem horário de verão desde 2019: UTC-3 fixo dispensa o banco de fusos (ausente na imagem slim).
BRASILIA = timezone(timedelta(hours=-3))

_EXPENSE_TOOLS = {"get_top_ceap_spender", "list_expense_categories", "check_parliamentary_expenses"}
_PARQUET_PROPOSITION_TOOLS = {"get_proposition_tramitation_history", "check_bill_apensamentos"}

_TSE_TABLES = {
    "resolve_candidate": "tse-consulta_cand_",
    "get_election_result": "tse-votacao_candidato_munzona_",
    "get_candidate_votes": "tse-votacao_candidato_munzona_",
    "check_candidate_status": "tse-consulta_cand_complementar_",
    "check_disqualification_motive": "tse-motivo_cassacao_",
    "check_candidate_profile": "tse-consulta_cand_",
    "get_candidate_assets": "tse-bem_candidato_",
    "check_cash_and_special_assets": "tse-bem_candidato_",
    "verify_official_social_media": "tse-rede_social_candidato_",  # 2022 vem uma fonte por UF
}

_cache: Dict[str, Tuple[Tuple[int, int], Optional[Dict[str, Any]]]] = {}


def load_ingestion_info() -> Optional[Dict[str, Any]]:
    """Lê o ingestion_info.json (de PROCESSED_DIR), relendo só quando o arquivo muda."""
    path = Path(os.environ.get("PROCESSED_DIR", "data/processed")) / INFO_FILE
    try:
        stat = path.stat()
    except OSError:
        _cache.pop(str(path), None)
        return None
    signature = (stat.st_mtime_ns, stat.st_size)
    cached = _cache.get(str(path))
    if cached and cached[0] == signature:
        return cached[1]
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = None
    _cache[str(path)] = (signature, info)
    return info


def _latest(fontes: Dict[str, Any], ids: List[str]) -> Optional[str]:
    dates = [fontes[i]["baixado_em"] for i in ids if i in fontes and fontes[i].get("baixado_em")]
    return max(dates) if dates else None


def _family(fontes: Dict[str, Any], prefix: str) -> List[str]:
    return [i for i in fontes if i.startswith(prefix)]


def data_date(
    tool_name: Optional[str],
    args: Optional[Dict[str, Any]],
    evidence: Optional[Dict[str, Any]],
    info: Optional[Dict[str, Any]],
) -> Optional[str]:
    """ISO da última atualização do dado que a tool leu, ou None quando não se aplica."""
    if not tool_name or not info or evidence_failed(evidence):
        return None
    fontes = info.get("fontes") or {}
    args = args or {}
    casa = str(args.get("casa") or (evidence or {}).get("casa") or "").strip().lower()

    if tool_name in _EXPENSE_TOOLS:
        prefix = {"camara": "camara-ceap-", "senado": "senado-ceaps-"}.get(casa)
        if not prefix:
            return None
        ano = args.get("ano")
        if ano is not None:
            exact = _latest(fontes, [f"{prefix}{ano}"])
            if exact:
                return exact
        return _latest(fontes, _family(fontes, prefix))

    if tool_name in _PARQUET_PROPOSITION_TOOLS:
        prefix = {"camara": "camara-proposicoes-", "senado": "senado-materias-"}.get(casa)
        return _latest(fontes, _family(fontes, prefix)) if prefix else None

    if tool_name in _TSE_TABLES:
        ano = args.get("ano")
        table = _TSE_TABLES[tool_name]
        return _latest(fontes, _family(fontes, f"{table}{ano}")) if ano is not None else None

    if tool_name == "resolve_politician":
        ids = ["camara-deputados", "senado-senadores"] + _family(fontes, "tse-consulta_cand_")
        return _latest(fontes, ids)

    return None


def format_data_date(iso: Optional[str]) -> Optional[str]:
    if not iso:
        return None
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(BRASILIA).strftime("%d/%m/%Y às %H:%M (horário de Brasília)")


def ensure_data_date_cited(text: str, iso: Optional[str]) -> str:
    """Acrescenta a data da base ao final do texto. A frase é a mesma para qualquer veredito (regra 6)."""
    formatted = format_data_date(iso)
    if not formatted:
        return text
    sentence = f"Base de dados consultada atualizada em {formatted}."
    if sentence in (text or ""):
        return text
    return f"{text} {sentence}".strip()
