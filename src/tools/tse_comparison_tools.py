"""Comparação de candidatos do TSE (``compare_candidates``).

O roteador executa uma tool por claim. Uma claim como "Lula gastou mais que Bolsonaro" precisa de dois
candidatos; esta tool recebe de dois a quatro ``SQ_CANDIDATO`` (o roteador resolve cada nome antes: regra 2),
consulta a mesma métrica de cada um com as tools que já existem e devolve tudo numa evidência só.

- Falta de dado de qualquer candidato impede a comparação (``dado_incompleto``): nunca vira zero (regra 1).
- Empate é declarado, sem líder (regra 6: sem palpite para nenhum lado).
- Disputas diferentes (cargo ou UF) são comparadas em número, mas o resultado avisa.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.tools.normalizer import normalize_text
from src.tools.tse_financas_tools import get_campaign_finances
from src.tools.tse_perfil_tools import get_candidate_assets
from src.tools.tse_tools import (
    _empty,
    _identity,
    _registered_candidate,
    election_results_available,
    get_candidate_votes,
    results_unavailable,
)

MIN_CANDIDATES, MAX_CANDIDATES = 2, 4
METRICS = ("votos_validos", "patrimonio", "receitas", "despesas_contratadas")
_UNITS = {"votos_validos": "votos", "patrimonio": "reais", "receitas": "reais", "despesas_contratadas": "reais"}


def comparison_spec_problem(metrica: Any, turno: Any, ano: Any) -> Optional[Dict[str, Any]]:
    """Evidência vazia se ano, métrica ou turno não especificam a comparação; ``None`` se está ok."""
    if not isinstance(ano, int) or isinstance(ano, bool):
        return _empty("especificacao_insuficiente", "Ano da eleição não informado; não foi possível comparar.")
    if metrica not in METRICS:
        return _empty("especificacao_insuficiente", f"Métrica '{metrica}' inválida. Use: {', '.join(METRICS)}.")
    if metrica == "votos_validos" and (turno not in (1, 2) or isinstance(turno, bool)):
        return _empty("especificacao_insuficiente", "Para comparar votos informe o turno (1 ou 2); ele não se adivinha.")
    return None


def _value(metrica: str, sq: int, ano: int, turno: Optional[int], base_dir: Optional[Path]) -> Dict[str, Any]:
    """Valor da métrica de um candidato, ou ``{"motivo": ...}`` se o dado não existe."""
    if metrica == "votos_validos":
        res = get_candidate_votes(sq, ano, turno, base_dir=base_dir)
        return {"valor": res["votos_validos"]} if res.get("encontrado") else {"motivo": res.get("motivo")}
    if metrica == "patrimonio":
        res = get_candidate_assets(sq, ano, base_dir=base_dir)
        if res.get("encontrado") and res.get("declarou_bens"):
            return {"valor": res["valor_total_declarado"]}
        return {"motivo": res.get("motivo") or res.get("aviso") or "Sem bens declarados."}
    res = get_campaign_finances(sq, ano, base_dir=base_dir)
    block = res.get("receitas" if metrica == "receitas" else "despesas_contratadas") or {}
    if res.get("encontrado") and block.get("total") is not None:
        return {"valor": block["total"], "aviso": res.get("aviso")}
    return {"motivo": res.get("motivo") or "Sem prestação de contas publicada para esta métrica."}


def compare_candidates(
    sq_candidatos: Any,
    ano: Optional[int],
    metrica: Optional[str],
    turno: Optional[int] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compara 2 a 4 candidatos (por ``SQ_CANDIDATO``) em votos válidos, patrimônio, receitas ou despesas."""
    if not isinstance(sq_candidatos, (list, tuple)):
        return _empty("especificacao_insuficiente", "Informe a lista de SQ_CANDIDATO dos candidatos a comparar.")
    if not MIN_CANDIDATES <= len(sq_candidatos) <= MAX_CANDIDATES:
        return _empty("especificacao_insuficiente",
                      f"Informe de {MIN_CANDIDATES} a {MAX_CANDIDATES} candidatos para comparar.")
    texts = [str(s).strip() if s is not None and not isinstance(s, bool) else "" for s in sq_candidatos]
    if not all(t.isdigit() for t in texts):
        return _empty("entidade_nao_resolvida",
                      "compare_candidates exige os SQ_CANDIDATO numéricos devolvidos por resolve_candidate (regra 2).")
    sqs = [int(t) for t in texts]
    if len(set(sqs)) != len(sqs):
        return _empty("especificacao_insuficiente", "Os candidatos a comparar precisam ser diferentes.")
    problem = comparison_spec_problem(metrica, turno, ano)
    if problem:
        return problem
    if metrica == "votos_validos" and not election_results_available(ano, base_dir):
        return results_unavailable(ano)

    registered = {sq: _registered_candidate(base_dir, sq, ano) for sq in sqs}
    missing = [sq for sq, frame in registered.items() if frame is None]
    if missing:
        return _empty("nao_encontrado", f"SQ_CANDIDATO {', '.join(map(str, missing))} não consta entre as candidaturas de {ano}.")

    entries: List[Dict[str, Any]] = []
    without_data: List[Dict[str, Any]] = []
    notices: List[str] = []
    for sq in sqs:
        identity = _identity(registered[sq], ano)
        got = _value(metrica, sq, ano, turno, base_dir)
        if "valor" in got:
            entries.append({"sq_candidato": sq, "nome_urna": identity["nome_urna"], "partido": identity["partido"],
                            "cargo": identity["cargo"], "uf": identity["uf"], "valor": got["valor"]})
            if got.get("aviso") and got["aviso"] not in notices:
                notices.append(got["aviso"])
        else:
            without_data.append({"sq_candidato": sq, "nome_urna": identity["nome_urna"], "motivo": got.get("motivo")})
    if without_data:
        return {**_empty("dado_incompleto", "Falta dado de pelo menos um candidato: a comparação não é feita (ausência não é zero)."),
                "metrica": metrica, "ano": ano, "candidatos_sem_dado": without_data}

    entries.sort(key=lambda e: (-e["valor"], e["sq_candidato"]))
    for position, entry in enumerate(entries, start=1):
        entry["posicao"] = position
    gap = entries[0]["valor"] - entries[1]["valor"]
    gap = round(gap, 2) if isinstance(gap, float) else gap
    tie = gap == 0
    same_dispute = len({(normalize_text(e["cargo"]), e["uf"]) for e in entries}) == 1
    if not same_dispute:
        notices.append("Os candidatos disputaram disputas diferentes (cargo ou UF): o número é comparável, a disputa não.")
    result: Dict[str, Any] = {
        "encontrado": True,
        "status": "ok",
        "metrica": metrica,
        "unidade": _UNITS[metrica],
        "ano": ano,
        "turno": turno if metrica == "votos_validos" else None,
        "candidatos": entries,
        "lider": None if tie else entries[0],
        "empate": tie,
        "diferenca_absoluta": gap,
        "mesma_disputa": same_dispute,
    }
    if notices:
        result["aviso"] = " ".join(notices)
    return result
