"""Tools de resultado eleitoral do TSE (Fase 1, passo 2 de docs/plan_cobertura_tools.md).

- ``resolve_candidate``: nome + ano (+ cargo, UF, número) -> ``SQ_CANDIDATO`` canônico, ou ambíguo (regra 2);
- ``get_election_result``: ranking de um cargo em um ano e turno, somando ``QT_VOTOS_NOMINAIS_VALIDOS``;
- ``get_candidate_votes``: votos de um candidato (por ``SQ_CANDIDATO``) em um ano e turno.

Esquema, sentinelas e homônimos: docs/data_schemas.md, seção 8. Os votos oficiais são os
``QT_VOTOS_NOMINAIS_VALIDOS``: ``QT_VOTOS_NOMINAIS`` inclui os anulados (candidatura indeferida). O voto no
exterior vem como UF ``ZZ`` e entra no total nacional. Toda evidência vazia traz ``encontrado: False`` e um
``status`` que explica o motivo (regra 3: sem ano, sem turno ou sem resultado publicado, não há palpite).
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import polars as pl
from rapidfuzz import fuzz

from src.tools.normalizer import normalize_text

logger = logging.getLogger("Tools.TSE")

FUZZY_THRESHOLD = 90.0
MAX_ALTERNATIVES = 10
DEFAULT_TOP_N = 10
SENTINELS = ("#NULO", "#NE", "#NULO#")

# Cargo normalizado -> nome canônico (como aparece em `votacao_munzona`).
_CARGOS = {
    "presidente": "Presidente",
    "governador": "Governador",
    "senador": "Senador",
    "deputado federal": "Deputado Federal",
    "deputado estadual": "Deputado Estadual",
    "deputado distrital": "Deputado Distrital",
}
# Só o cargo nacional tem um único recorte sem UF.
_CARGOS_NACIONAIS = {"Presidente"}


def _tse_root(base_dir: Optional[Path]) -> Path:
    return (Path(base_dir) if base_dir else Path("data/processed")) / "tse"


def _scan(base_dir: Optional[Path], table: str, ano: int) -> Optional[pl.LazyFrame]:
    """Parquet do ano de uma tabela do TSE (lazy: a votação tem milhões de linhas), ou None se não existe."""
    folder = _tse_root(base_dir) / table / f"ano={ano}"
    files = sorted(folder.glob("*.parquet")) if folder.exists() else []
    if not files:
        return None
    return pl.scan_parquet([str(f) for f in files])


def _read(base_dir: Optional[Path], table: str, ano: int, filters: Optional[List[pl.Expr]] = None) -> Optional[pl.DataFrame]:
    """Materializa a tabela com os filtros aplicados antes da leitura; None se ausente ou ilegível."""
    lf = _scan(base_dir, table, ano)
    if lf is None:
        return None
    try:
        for expr in filters or []:
            lf = lf.filter(expr)
        return lf.collect()
    except Exception as exc:  # noqa: BLE001 - parquet corrompido vira "sem dado", não derruba o roteador
        logger.error("Erro ao ler %s (ano %s): %s", table, ano, exc, exc_info=True)
        return None


def _clean(value: Any) -> Any:
    """Marcadores do TSE (#NULO, #NE) são ausência de valor, nunca valor."""
    return None if isinstance(value, str) and value in SENTINELS else value


def _canonical_cargo(cargo: Optional[str]) -> Optional[str]:
    return _CARGOS.get(normalize_text(cargo)) if cargo else None


def _empty(status: str, motivo: str, **extra: Any) -> Dict[str, Any]:
    return {"encontrado": False, "status": status, "motivo": motivo, **extra}


def _valid_year_turn(ano: Any, turno: Any) -> Optional[Dict[str, Any]]:
    """Guarda de especificidade (regra 3): ano e turno são obrigatórios e não se adivinham."""
    if not isinstance(ano, int) or isinstance(ano, bool):
        return _empty("especificacao_insuficiente", "Ano da eleição não informado; não foi possível consultar.")
    if turno not in (1, 2) or isinstance(turno, bool):
        return _empty("especificacao_insuficiente", "Turno não informado ou inválido (use 1 ou 2); não foi possível consultar.")
    return None


# --------------------------------------------------------------------------- resolve_candidate

def _summary(row: Dict[str, Any], turnos: List[int]) -> Dict[str, Any]:
    return {
        "sq_candidato": int(row["SQ_CANDIDATO"]),
        "nome_civil": row.get("NM_CANDIDATO"),
        "nome_urna": row.get("NM_URNA_CANDIDATO"),
        "nome_social": _clean(row.get("NM_SOCIAL_CANDIDATO")),
        "partido": row.get("SG_PARTIDO"),
        "cargo": row.get("DS_CARGO"),
        "uf": row.get("SG_UF"),
        "numero": row.get("NR_CANDIDATO"),
        "ano": row.get("ANO_ELEICAO"),
        "turnos": turnos,
    }


def _unique_candidacies(df: pl.DataFrame) -> List[Dict[str, Any]]:
    """Uma entrada por ``SQ_CANDIDATO``: o 2º turno repete a linha, e isso não é homonímia."""
    turnos: Dict[int, List[int]] = {}
    first: Dict[int, Dict[str, Any]] = {}
    for row in df.iter_rows(named=True):
        sq = int(row["SQ_CANDIDATO"])
        first.setdefault(sq, row)
        turno = row.get("NR_TURNO")
        if turno is not None and turno not in turnos.setdefault(sq, []):
            turnos[sq].append(int(turno))
    return [_summary(first[sq], sorted(turnos.get(sq, []))) for sq in first]


def _name_stages(query: str, candidates: List[Dict[str, Any]]):
    """Gera, do mais ao menos estrito, os candidatos que casam com o nome buscado."""
    names = []
    for cand in candidates:
        norms = {normalize_text(cand.get(k)) for k in ("nome_urna", "nome_civil", "nome_social")}
        names.append((cand, {n for n in norms if n}))

    yield "exato", [c for c, norms in names if query in norms]

    q_tokens = set(query.split())
    yield "tokens", [c for c, norms in names if any(q_tokens <= set(n.split()) for n in norms)]

    scored = [(max(fuzz.token_sort_ratio(query, n) for n in norms), c) for c, norms in names if norms]
    yield "fuzzy", [c for score, c in scored if score >= FUZZY_THRESHOLD]


def resolve_candidate(
    nome_busca: str,
    ano: Optional[int],
    cargo: Optional[str] = None,
    uf: Optional[str] = None,
    numero: Optional[int] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Resolve o nome de um candidato (nome de urna, civil ou social) para o ``SQ_CANDIDATO`` do ano.

    Homônimos (mesmo nome, UF e cargo) devolvem ``ambiguous: True`` com as alternativas; o ``numero`` na urna
    ou o nome civil desempatam. Nunca escolhe entre candidatos igualmente prováveis (regra 2).
    """
    if not isinstance(ano, int) or isinstance(ano, bool):
        return _empty("especificacao_insuficiente", "Ano da eleição não informado; o SQ_CANDIDATO só é único dentro do ano.",
                      sq_candidato=None, ambiguous=False, candidatos_alternativos=[])

    query = normalize_text(nome_busca if isinstance(nome_busca, str) else "")
    base = {"sq_candidato": None, "ambiguous": False, "candidatos_alternativos": [], "ano": ano}
    if len(query) < 2:
        return _empty("nao_encontrado", "Nome do candidato ausente ou curto demais.", **base)

    df = _read(base_dir, "candidatos", ano)
    if df is None:
        return _empty("nao_encontrado", f"Sem base de candidatos do TSE para {ano}.", **base)

    if cargo:
        wanted = normalize_text(cargo)
        df = df.filter(pl.col("DS_CARGO").map_elements(normalize_text, return_dtype=pl.Utf8) == wanted)
    if uf:
        df = df.filter(pl.col("SG_UF") == uf.strip().upper())
    if numero is not None:
        df = df.filter(pl.col("NR_CANDIDATO") == int(numero))
    candidates = _unique_candidacies(df)

    for stage, matches in _name_stages(query, candidates):
        if not matches:
            continue
        if len(matches) == 1:
            return {"encontrado": True, "status": "resolvido", **matches[0],
                    "ambiguous": False, "candidatos_alternativos": [], "etapa": stage}
        return {**_empty("ambiguo", f"{len(matches)} candidaturas com esse nome em {ano}; informe cargo, UF ou número.", **base),
                "ambiguous": True, "total_candidatos": len(matches),
                "candidatos_alternativos": matches[:MAX_ALTERNATIVES]}

    return _empty("nao_encontrado", f"Nenhum candidato de {ano} corresponde a '{nome_busca}'.", **base)


# --------------------------------------------------------------------------- votos

_VOTE_COLUMNS = ["NR_TURNO", "SG_UF", "DS_CARGO", "SQ_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO",
                 "QT_VOTOS_NOMINAIS", "QT_VOTOS_NOMINAIS_VALIDOS", "DS_SIT_TOT_TURNO"]


def _valid_votes_frame(base_dir: Optional[Path], ano: int, turno: int,
                       filters: Optional[List[pl.Expr]] = None) -> Optional[pl.DataFrame]:
    """Votos do turno (e demais filtros) lidos só com as colunas usadas, para caber na memória."""
    lf = _scan(base_dir, "votacao_munzona", ano)
    if lf is None:
        return None
    try:
        lf = lf.select(_VOTE_COLUMNS).filter(pl.col("NR_TURNO") == turno)
        for expr in filters or []:
            lf = lf.filter(expr)
        return lf.collect()
    except Exception as exc:  # noqa: BLE001
        logger.error("Erro ao ler votacao_munzona (ano %s): %s", ano, exc, exc_info=True)
        return None


def _unavailable(ano: int) -> Dict[str, Any]:
    if ano >= 2026:
        motivo = f"O TSE ainda não publicou resultado de votação para {ano}; só candidaturas, bens e prestação de contas."
    else:
        motivo = f"Sem base de votação do TSE para {ano}."
    return _empty("resultado_indisponivel", motivo, candidatos=[])


def _per_candidate(df: pl.DataFrame) -> pl.DataFrame:
    return (
        df.group_by("SQ_CANDIDATO")
        .agg(
            pl.col("NM_URNA_CANDIDATO").first().alias("nome_urna"),
            pl.col("SG_PARTIDO").first().alias("partido"),
            pl.col("DS_CARGO").first().alias("cargo"),
            pl.col("SG_UF").first().alias("uf_votacao"),
            pl.col("DS_SIT_TOT_TURNO").first().alias("situacao"),
            pl.col("QT_VOTOS_NOMINAIS").sum().alias("votos_nominais"),
            pl.col("QT_VOTOS_NOMINAIS_VALIDOS").sum().alias("votos_validos"),
        )
        .sort(["votos_validos", "SQ_CANDIDATO"], descending=[True, False])
    )


def _entry(row: Dict[str, Any], posicao: int, total: int) -> Dict[str, Any]:
    validos, nominais = int(row["votos_validos"]), int(row["votos_nominais"])
    return {
        "posicao": posicao,
        "sq_candidato": int(row["SQ_CANDIDATO"]),
        "nome_urna": row["nome_urna"],
        "partido": row["partido"],
        "situacao": _clean(row["situacao"]),
        "votos_validos": validos,
        "votos_nominais": nominais,
        "votos_anulados": nominais - validos,
        "percentual_votos_validos": round(validos / total * 100, 2) if total else None,
    }


def get_election_result(
    cargo: str,
    ano: Optional[int],
    turno: Optional[int],
    uf: Optional[str] = None,
    top_n: int = DEFAULT_TOP_N,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Ranking de um cargo em um ano e turno, por votos válidos. Cargo estadual ou legislativo exige UF."""
    guard = _valid_year_turn(ano, turno)
    if guard:
        return {**guard, "candidatos": []}
    canonical = _canonical_cargo(cargo)
    if canonical is None:
        return _empty("cargo_invalido", f"Cargo '{cargo}' desconhecido. Use: {', '.join(_CARGOS.values())}.", candidatos=[])
    uf_clean = uf.strip().upper() if isinstance(uf, str) and uf.strip() else None
    if canonical not in _CARGOS_NACIONAIS and not uf_clean:
        return _empty("especificacao_insuficiente", f"{canonical} é eleito por UF; informe a UF para consultar o resultado.", candidatos=[])

    filters = [pl.col("DS_CARGO") == canonical]
    if canonical not in _CARGOS_NACIONAIS:
        filters.append(pl.col("SG_UF") == uf_clean)
    df = _valid_votes_frame(base_dir, ano, turno, filters)
    if df is None:
        return _unavailable(ano)
    if df.is_empty():
        return _empty("sem_resultado", f"Não há votação de {canonical} no {turno}º turno de {ano}"
                      + (f" em {uf_clean}." if uf_clean else "."), candidatos=[])

    ranking = _per_candidate(df)
    total = int(ranking["votos_validos"].sum())
    entries = [_entry(row, pos, total) for pos, row in enumerate(ranking.iter_rows(named=True), start=1)]
    return {
        "encontrado": True,
        "status": "ok",
        "cargo": canonical,
        "ano": ano,
        "turno": turno,
        "uf": uf_clean,
        "total_votos_validos": total,
        "total_candidatos": len(entries),
        "candidatos": entries[: max(int(top_n), 1)],
        "eleitos": [e for e in entries if (e["situacao"] or "").startswith("ELEITO")],
    }


def get_candidate_votes(
    sq_candidato: Any,
    ano: Optional[int],
    turno: Optional[int],
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Votos válidos, anulados e posição de um candidato já resolvido (``SQ_CANDIDATO``) em um ano e turno."""
    sq_text = str(sq_candidato).strip() if sq_candidato is not None and not isinstance(sq_candidato, bool) else ""
    if not sq_text.isdigit():
        return _empty("entidade_nao_resolvida",
                      "get_candidate_votes exige o SQ_CANDIDATO numérico devolvido por resolve_candidate (regra 2).")
    sq = int(sq_text)
    guard = _valid_year_turn(ano, turno)
    if guard:
        return guard

    own = _valid_votes_frame(base_dir, ano, turno, [pl.col("SQ_CANDIDATO") == sq])
    if own is None:
        return _unavailable(ano)
    if own.is_empty():
        known = _read(base_dir, "candidatos", ano)
        if known is None or known.filter(pl.col("SQ_CANDIDATO") == sq).is_empty():
            return _empty("nao_encontrado", f"SQ_CANDIDATO {sq} não consta entre as candidaturas de {ano}.")
        return _empty("sem_resultado", f"O candidato {sq} não tem votos registrados no {turno}º turno de {ano}.")

    cargo, uf = own["DS_CARGO"][0], own["SG_UF"][0]
    scope_filters = [pl.col("DS_CARGO") == cargo]
    if cargo not in _CARGOS_NACIONAIS:
        scope_filters.append(pl.col("SG_UF") == uf)
    scope = _valid_votes_frame(base_dir, ano, turno, scope_filters)
    ranking = _per_candidate(scope)
    total = int(ranking["votos_validos"].sum())
    for pos, row in enumerate(ranking.iter_rows(named=True), start=1):
        if int(row["SQ_CANDIDATO"]) == sq:
            return {
                "encontrado": True,
                "status": "ok",
                **_entry(row, pos, total),
                "cargo": cargo,
                "uf": None if cargo in _CARGOS_NACIONAIS else uf,
                "ano": ano,
                "turno": turno,
                "total_votos_validos_cargo": total,
                "total_candidatos_cargo": ranking.height,
            }
    raise AssertionError("o candidato está em `own`, logo no recorte do cargo")  # pragma: no cover
