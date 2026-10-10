"""Tools de finanças de campanha do TSE (Fase 1, passo 4 de docs/plan_cobertura_tools.md).

- ``get_campaign_finances``: receitas, despesas contratadas e despesas pagas de um candidato;
- ``get_top_campaign_finances``: ranking de um cargo por receitas ou despesas contratadas.

Fonte: ``prestacao_contas/{receitas,despesas_contratadas,despesas_pagas}`` (docs/data_schemas.md 8.3). A
``despesas_pagas`` não tem candidato: liga-se por ``SQ_PRESTADOR_CONTAS``, que é 1:1 com o candidato. Cada
candidato tem um único tipo de prestação e um único prestador no ano, então somar as linhas não duplica.
Doadores e fornecedores (pessoas físicas, CPF/CNPJ) nunca saem; só agregados.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import polars as pl

from src.tools.tse_tools import (
    _CARGOS,
    _candidate_guard,
    _canonical_cargo,
    _clean,
    _empty,
    _identity,
    _registered_candidate,
    _scan,
)

TOP_BREAKDOWN = 8
MAX_TOP_N = 50
DEFAULT_TOP_N = 5
_METRICS = {"receitas": ("receitas", "VR_RECEITA"),
            "despesas_contratadas": ("despesas_contratadas", "VR_DESPESA_CONTRATADA")}

_PARTIAL_NOTICE = ("A prestação de contas deste candidato ainda não é a final (tipo {tipo}): os valores são parciais "
                   "e podem mudar.")


def _table(base_dir: Optional[Path], name: str, ano: int) -> Optional[pl.LazyFrame]:
    return _scan(base_dir, f"prestacao_contas/{name}", ano)


def _breakdown(df: pl.DataFrame, column: str, key: str) -> List[Dict[str, Any]]:
    """Soma por categoria, maiores primeiro, sem o marcador ``#NULO`` do TSE."""
    if df.is_empty():
        return []
    grouped = (
        df.filter(pl.col(column).is_not_null() & (pl.col(column) != "#NULO"))
        .group_by(column)
        .agg(pl.col("valor").sum())
        .sort(["valor", column], descending=[True, False])
    )
    return [{key: r[column], "valor": round(float(r["valor"]), 2)} for r in grouped.head(TOP_BREAKDOWN).iter_rows(named=True)]


def _total(df: pl.DataFrame) -> Dict[str, Any]:
    return {"quantidade": df.height, "total": round(float(df["valor"].sum()), 2) if df.height else 0.0}


def get_campaign_finances(sq_candidato: Any, ano: Optional[int], base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Totais de receitas e despesas declaradas na prestação de contas da campanha de um candidato."""
    sq, problem = _candidate_guard(sq_candidato, ano)
    if problem:
        return problem
    cadastro = _registered_candidate(base_dir, sq, ano)
    if cadastro is None:
        return _empty("nao_encontrado", f"SQ_CANDIDATO {sq} não consta entre as candidaturas de {ano}.")

    rec_lf, desp_lf, pagas_lf = (_table(base_dir, n, ano) for n in ("receitas", "despesas_contratadas", "despesas_pagas"))
    if rec_lf is None and desp_lf is None:
        return _empty("resultado_indisponivel", f"Sem base de prestação de contas do TSE para {ano}.", ano=ano)

    receitas = ((rec_lf.filter(pl.col("SQ_CANDIDATO") == sq).select(
        "SQ_PRESTADOR_CONTAS", "TP_PRESTACAO_CONTAS", "DS_ORIGEM_RECEITA", "DS_FONTE_RECEITA",
        pl.col("VR_RECEITA").alias("valor")).collect()) if rec_lf is not None else None)
    despesas = ((desp_lf.filter(pl.col("SQ_CANDIDATO") == sq).select(
        "SQ_PRESTADOR_CONTAS", "TP_PRESTACAO_CONTAS", "DS_ORIGEM_DESPESA",
        pl.col("VR_DESPESA_CONTRATADA").alias("valor")).collect()) if desp_lf is not None else None)

    frames = [f for f in (receitas, despesas) if f is not None and not f.is_empty()]
    if not frames:
        return _empty("sem_prestacao", f"Não há prestação de contas publicada para o candidato {sq} em {ano}; "
                      "isso não significa gasto ou receita zero.")
    prestadores = sorted({p for f in frames for p in f["SQ_PRESTADOR_CONTAS"].drop_nulls().to_list()})
    tipos = [t for f in frames for t in f["TP_PRESTACAO_CONTAS"].drop_nulls().unique().to_list()]
    tipo = _clean(tipos[0]) if tipos else None

    pagas = ((pagas_lf.filter(pl.col("SQ_PRESTADOR_CONTAS").is_in(prestadores)).select(
        pl.col("VR_PAGTO_DESPESA").alias("valor")).collect()) if pagas_lf is not None else None)

    result: Dict[str, Any] = {
        "encontrado": True,
        "status": "ok",
        **_identity(cadastro, ano),
        "tipo_prestacao": tipo,
        "prestacao_final": tipo == "FINAL",
        "receitas": ({**_total(receitas), "por_origem": _breakdown(receitas, "DS_ORIGEM_RECEITA", "origem"),
                      "por_fonte": _breakdown(receitas, "DS_FONTE_RECEITA", "fonte")}
                     if receitas is not None else {"quantidade": None, "total": None, "por_origem": [], "por_fonte": []}),
        "despesas_contratadas": ({**_total(despesas), "por_categoria": _breakdown(despesas, "DS_ORIGEM_DESPESA", "categoria")}
                                 if despesas is not None else {"quantidade": None, "total": None, "por_categoria": []}),
        "despesas_pagas": _total(pagas) if pagas is not None else {"quantidade": None, "total": None},
    }
    if tipo != "FINAL":
        result["aviso"] = _PARTIAL_NOTICE.format(tipo=tipo or "não informado")
    return result


def get_top_campaign_finances(
    cargo: str,
    ano: Optional[int],
    metrica: str = "despesas_contratadas",
    uf: Optional[str] = None,
    top_n: int = DEFAULT_TOP_N,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Ranking dos candidatos de um cargo (e UF, se informada) por receitas ou despesas contratadas."""
    if not isinstance(ano, int) or isinstance(ano, bool):
        return _empty("especificacao_insuficiente", "Ano da eleição não informado; não foi possível consultar.", candidatos=[])
    if metrica not in _METRICS:
        return _empty("especificacao_insuficiente", f"Métrica '{metrica}' inválida. Use: {', '.join(_METRICS)}.", candidatos=[])
    canonical = _canonical_cargo(cargo)
    if canonical is None:
        return _empty("cargo_invalido", f"Cargo '{cargo}' desconhecido. Use: {', '.join(_CARGOS.values())}.", candidatos=[])

    table, column = _METRICS[metrica]
    lf = _table(base_dir, table, ano)
    if lf is None:
        return _empty("resultado_indisponivel", f"Sem base de {table} do TSE para {ano}.", ano=ano, candidatos=[])

    uf_clean = uf.strip().upper() if isinstance(uf, str) and uf.strip() else None
    lf = lf.filter(pl.col("DS_CARGO") == canonical)
    if uf_clean:
        lf = lf.filter(pl.col("SG_UF") == uf_clean)
    ranking = (
        lf.group_by("SQ_CANDIDATO")
        .agg(pl.col("NM_CANDIDATO").first().alias("nome"), pl.col("SG_PARTIDO").first().alias("partido"),
             pl.col("SG_UF").first().alias("uf"), pl.col("TP_PRESTACAO_CONTAS").first().alias("tipo"),
             pl.col(column).sum().alias("valor"))
        .sort(["valor", "SQ_CANDIDATO"], descending=[True, False])
        .collect()
    )
    if ranking.is_empty():
        return _empty("sem_resultado", f"Não há prestação de contas de {canonical} em {ano}"
                      + (f" em {uf_clean}." if uf_clean else "."), candidatos=[])

    entries = [
        {"posicao": pos, "sq_candidato": int(r["SQ_CANDIDATO"]), "nome": r["nome"], "partido": r["partido"],
         "uf": r["uf"], "tipo_prestacao": _clean(r["tipo"]), "valor": round(float(r["valor"]), 2)}
        for pos, r in enumerate(ranking.iter_rows(named=True), start=1)
    ]
    result: Dict[str, Any] = {
        "encontrado": True, "status": "ok", "cargo": canonical, "ano": ano, "uf": uf_clean, "metrica": metrica,
        "total_candidatos": len(entries), "valor_total_cargo": round(float(ranking["valor"].sum()), 2),
        "candidatos": entries[: max(1, min(int(top_n), MAX_TOP_N))],
    }
    if any(e["tipo_prestacao"] != "FINAL" for e in entries):
        result["aviso"] = ("Há candidatos cuja prestação de contas ainda não é a final (parcial): os valores podem "
                           "mudar.")
    return result
