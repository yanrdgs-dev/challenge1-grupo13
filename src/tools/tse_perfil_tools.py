"""Tools de perfil e patrimônio do TSE (Fase 1, passo 3 de docs/plan_cobertura_tools.md).

- ``check_candidate_profile``: gênero, instrução, estado civil, cor/raça, ocupação, naturalidade, idade na posse;
- ``get_candidate_assets``: bens declarados (total, composição, maior bem);
- ``check_cash_and_special_assets``: dinheiro em espécie e bens especiais (aeronave, embarcação, joias, ouro);
- ``verify_official_social_media``: links de rede social que o candidato registrou no TSE.

Todas recebem o ``SQ_CANDIDATO`` canônico (regra 2). CPF, título, e-mail e data de nascimento nunca saem.
Ausência de linha em ``bens`` não é patrimônio zero declarado (docs/data_schemas.md 8.3).
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import polars as pl

from src.tools.normalizer import normalize_text
from src.tools.tse_tools import (
    _candidate_guard,
    _clean,
    _empty,
    _identity,
    _read,
    _registered_candidate,
    check_candidate_status,
)

_NOT_DISCLOSED = "nao divulgavel"
TOP_TYPES = 10

_CASH_TYPES = {"Dinheiro em espécie - moeda nacional", "Dinheiro em espécie - moeda estrangeira"}
_SPECIAL_TYPES = (
    "Aeronave", "Embarcação", "Jóia, quadro, objeto de arte, de coleção, antiguidade, etc.", "Ouro, ativo financeiro",
)


def _value(raw: Any) -> Any:
    """Valor de perfil: marcadores do TSE e "Não divulgável" são ausência de dado."""
    raw = _clean(raw)
    if isinstance(raw, str) and (not raw.strip() or normalize_text(raw) == _NOT_DISCLOSED):
        return None
    return raw


def _flag(raw: Any) -> Optional[bool]:
    raw = _value(raw)
    return {"S": True, "N": False}.get(raw.strip().upper()) if isinstance(raw, str) else None


def _int(raw: Any) -> Optional[int]:
    raw = _value(raw)
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None  # -1/-3/-4 são sentinelas numéricas


def _resolved(sq_candidato: Any, ano: Any, base_dir: Optional[Path]):
    """Guardas comuns: ID canônico, ano e candidatura no cadastro. ``(sq, cadastro, None)`` ou ``(.., problema)``."""
    sq, problem = _candidate_guard(sq_candidato, ano)
    if problem:
        return None, None, problem
    cadastro = _registered_candidate(base_dir, sq, ano)
    if cadastro is None:
        return None, None, _empty("nao_encontrado", f"SQ_CANDIDATO {sq} não consta entre as candidaturas de {ano}.")
    return sq, cadastro, None


# --------------------------------------------------------------------------- perfil

def check_candidate_profile(sq_candidato: Any, ano: Optional[int], base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Perfil declarado ao TSE. Campos "Não divulgável" ou ausentes voltam como ``None``."""
    sq, cadastro, problem = _resolved(sq_candidato, ano, base_dir)
    if problem:
        return problem
    row = cadastro.row(0, named=True)
    extra = _read(base_dir, "candidatos_complementar", ano, [pl.col("SQ_CANDIDATO") == sq])
    extra_row = extra.row(0, named=True) if extra is not None and not extra.is_empty() else {}
    return {
        "encontrado": True,
        "status": "ok",
        **_identity(cadastro, ano),
        "genero": _value(row.get("DS_GENERO")),
        "grau_instrucao": _value(row.get("DS_GRAU_INSTRUCAO")),
        "estado_civil": _value(row.get("DS_ESTADO_CIVIL")),
        "cor_raca": _value(row.get("DS_COR_RACA")),
        "ocupacao": _value(row.get("DS_OCUPACAO")),
        "uf_nascimento": _value(row.get("SG_UF_NASCIMENTO")),
        "idade_na_posse": _int(extra_row.get("NR_IDADE_DATA_POSSE")),
        "reeleicao": _flag(extra_row.get("ST_REELEICAO")),
        "nacionalidade": _value(extra_row.get("DS_NACIONALIDADE")),
    }


# --------------------------------------------------------------------------- patrimônio

def _assets(base_dir: Optional[Path], sq: int, ano: int) -> Optional[pl.DataFrame]:
    return _read(base_dir, "bens", ano, [pl.col("SQ_CANDIDATO") == sq])


_NO_ASSETS_NOTICE = ("Nenhum bem consta na declaração deste candidato no TSE. Isso não é patrimônio zero declarado: "
                     "pode não ter declarado, ou a declaração não foi publicada.")


def get_candidate_assets(sq_candidato: Any, ano: Optional[int], base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Bens declarados: total, quantidade, composição por tipo e maior bem."""
    sq, cadastro, problem = _resolved(sq_candidato, ano, base_dir)
    if problem:
        return problem
    bens = _assets(base_dir, sq, ano)
    if bens is None:
        return _empty("resultado_indisponivel", f"Sem base de bens declarados do TSE para {ano}.", ano=ano)
    identity = _identity(cadastro, ano)
    if bens.is_empty():
        return {"encontrado": True, "status": "ok", **identity, "declarou_bens": False, "quantidade_bens": 0,
                "valor_total_declarado": None, "bens_valor_zero": 0, "bens_valor_negativo": 0, "por_tipo": [],
                "maior_bem": None, "aviso": _NO_ASSETS_NOTICE}

    por_tipo = (
        bens.group_by("DS_TIPO_BEM_CANDIDATO")
        .agg(pl.len().alias("quantidade"), pl.col("VR_BEM_CANDIDATO").sum().alias("valor"))
        .sort(["valor", "DS_TIPO_BEM_CANDIDATO"], descending=[True, False])
    )
    biggest = bens.sort("VR_BEM_CANDIDATO", descending=True).row(0, named=True)
    return {
        "encontrado": True,
        "status": "ok",
        **identity,
        "declarou_bens": True,
        "quantidade_bens": bens.height,
        "valor_total_declarado": round(float(bens["VR_BEM_CANDIDATO"].sum()), 2),
        "bens_valor_zero": int((bens["VR_BEM_CANDIDATO"] == 0).sum()),
        "bens_valor_negativo": int((bens["VR_BEM_CANDIDATO"] < 0).sum()),
        "por_tipo": [
            {"tipo": r["DS_TIPO_BEM_CANDIDATO"], "quantidade": r["quantidade"], "valor": round(float(r["valor"]), 2)}
            for r in por_tipo.head(TOP_TYPES).iter_rows(named=True)
        ],
        "maior_bem": {"tipo": biggest["DS_TIPO_BEM_CANDIDATO"], "descricao": (biggest["DS_BEM_CANDIDATO"] or "").strip(),
                      "valor": round(float(biggest["VR_BEM_CANDIDATO"]), 2)},
    }


def check_cash_and_special_assets(sq_candidato: Any, ano: Optional[int], base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Dinheiro em espécie (nacional e estrangeiro) e bens especiais declarados (aeronave, embarcação, joias, ouro)."""
    sq, cadastro, problem = _resolved(sq_candidato, ano, base_dir)
    if problem:
        return problem
    bens = _assets(base_dir, sq, ano)
    if bens is None:
        return _empty("resultado_indisponivel", f"Sem base de bens declarados do TSE para {ano}.", ano=ano)
    identity = _identity(cadastro, ano)
    if bens.is_empty():
        return {"encontrado": True, "status": "ok", **identity, "declarou_bens": False,
                "dinheiro_em_especie": {"quantidade": 0, "valor": None}, "bens_especiais": [], "aviso": _NO_ASSETS_NOTICE}

    cash = bens.filter(pl.col("DS_TIPO_BEM_CANDIDATO").is_in(list(_CASH_TYPES)))
    special = []
    for categoria in _SPECIAL_TYPES:
        rows = bens.filter(pl.col("DS_TIPO_BEM_CANDIDATO") == categoria)
        if not rows.is_empty():
            special.append({"categoria": categoria, "quantidade": rows.height,
                            "valor": round(float(rows["VR_BEM_CANDIDATO"].sum()), 2)})
    return {
        "encontrado": True,
        "status": "ok",
        **identity,
        "declarou_bens": True,
        "dinheiro_em_especie": {"quantidade": cash.height, "valor": round(float(cash["VR_BEM_CANDIDATO"].sum()), 2)},
        "bens_especiais": special,
    }


# --------------------------------------------------------------------------- redes sociais

_NETWORKS = (
    ("instagram", ("instagram.com", "instagr.am")),
    ("twitter", ("twitter.com", "x.com")),
    ("facebook", ("facebook.com", "fb.com", "fb.me")),
    ("youtube", ("youtube.com", "youtu.be")),
    ("tiktok", ("tiktok.com",)),
    ("kwai", ("kwai.com",)),
    ("linkedin", ("linkedin.com",)),
    ("telegram", ("t.me", "telegram.me")),
    ("whatsapp", ("wa.me", "whatsapp.com")),
)


def _canonical_url(url: str) -> str:
    """Forma comparável do link: sem esquema, ``www.``, parâmetros, barra final, em minúsculas."""
    text = url.strip().lower()
    text = re.sub(r"^[a-z]+://", "", text)
    text = re.sub(r"^www\.", "", text)
    return re.split(r"[?#]", text)[0].rstrip("/")


def _network(canonical: str) -> str:
    host = canonical.split("/")[0]
    for name, hosts in _NETWORKS:
        if any(host == h or host.endswith("." + h) for h in hosts):
            return name
    return "outra"


def verify_official_social_media(
    sq_candidato: Any, ano: Optional[int], termo: Optional[str] = None, base_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """Links de rede social que o candidato registrou no TSE; ``termo`` (perfil ou URL) diz se está entre eles.

    Só vale para o que foi registrado na candidatura: não prova que um perfil é falso nem que é verdadeiro fora dela.
    """
    sq, cadastro, problem = _resolved(sq_candidato, ano, base_dir)
    if problem:
        return problem
    rows = _read(base_dir, "redes_sociais", ano, [pl.col("SQ_CANDIDATO") == sq])
    if rows is None:
        return _empty("resultado_indisponivel", f"Sem base de redes sociais do TSE para {ano}.", ano=ano)

    links: List[Dict[str, Any]] = []
    seen = set()
    for row in rows.sort("NR_ORDEM").iter_rows(named=True):
        url = _value(row.get("DS_URL"))
        if not url:
            continue
        canonical = _canonical_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        links.append({"rede": _network(canonical), "url": url.strip(), "ordem": row.get("NR_ORDEM")})

    result: Dict[str, Any] = {
        "encontrado": True, "status": "ok", **_identity(cadastro, ano), "links": links, "total_links": len(links),
        "aviso": "Só constam os links registrados pelo candidato no TSE na candidatura; não é um cadastro de todos os perfis.",
    }
    if termo is not None:
        needle = termo.strip().lower().lstrip("@").rstrip("/")
        match = next((l for l in links if needle and needle in _canonical_url(l["url"])), None)
        result["termo_consultado"] = termo
        result["termo_registrado"] = match is not None
        result["link_correspondente"] = match
    return result
