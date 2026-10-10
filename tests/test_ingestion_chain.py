"""Cadeia real build_parquet -> dim_politicos sobre amostras reais pequenas e sanitizadas (sem CPF, e-mail etc.).

Pega desencontros entre o formato que as fontes entregam e o que o dim_politicos espera, que testes com
dados sintéticos não pegam.
"""

import shutil
from pathlib import Path

import polars as pl
import pytest

from src.etl.build_dim_politicos import build_and_save_dim_politicos
from src.etl.build_parquet import process_all_datasets
from src.etl.senado_cadastro import normalize_senado_senadores

FIX = Path(__file__).parent / "fixtures" / "ingestion"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("chain")
    ds, out = tmp / "datasets", tmp / "processed"
    layout = {
        "deputados.csv": "camara/cadastro",
        "Ano-2026.csv": "camara/ceap",
        "senadores.csv": "senado/cadastro",
        "consulta_cand_2026_BRASIL.csv": "tse/candidatos",
        "consulta_cand_complementar_2026_BRASIL.csv": "tse/candidatos",
    }
    for name, sub in layout.items():
        (ds / sub).mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / name, ds / sub / name)
    failures = []
    process_all_datasets(datasets_dir=ds, output_base=out, failures=failures)
    assert failures == [], failures
    dim = build_and_save_dim_politicos(
        output_path=str(out / "dim_politicos.parquet"),
        camara_deputados_path=str(out / "camara" / "deputados.parquet"),
        senado_senadores_path=str(out / "senado" / "senadores.parquet"),
        camara_ceap_pattern=str(out / "camara" / "ceap" / "**" / "*.parquet"),
        tse_candidatos_pattern=str(out / "tse" / "candidatos" / "**" / "*.parquet"),
    )
    return {"out": out, "dim": pl.read_parquet(dim)}


def test_samples_contain_no_personal_identifiers():
    for f in FIX.glob("*.csv"):
        raw = f.read_bytes().decode("latin1")
        import re

        assert not re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}", raw), f"CPF em {f.name}"
        assert "@" not in raw, f"e-mail em {f.name}"


def test_ceap_keeps_the_join_key_dim_politicos_needs(built):
    ceap = pl.read_parquet(next((built["out"] / "camara" / "ceap").rglob("*.parquet")))
    assert "ideCadastro" in ceap.columns


def test_senadores_are_one_row_per_senator_with_the_columns_dim_politicos_reads(built):
    sen = pl.read_parquet(built["out"] / "senado" / "senadores.parquet")
    assert sen.height == 2  # a fonte traz uma linha por suplente/exercício; são 2 senadores
    assert {"Nome Parlamentar", "UF", "Partido", "Mandato"} <= set(sen.columns)
    alan = sen.filter(pl.col("Nome Parlamentar") == "Alan Rick").to_dicts()[0]
    assert alan["UF"] == "AC" and alan["Partido"] == "REPUBLICANOS" and alan["Mandato"] == "2023-2031"


def test_dim_politicos_has_both_houses_without_duplicates(built):
    dim = built["dim"]
    assert dim["casa"].value_counts().sort("casa").to_dicts() == [
        {"casa": "Câmara dos Deputados", "count": 3}, {"casa": "Senado Federal", "count": 2}]
    assert dim.select("nome_normalizado", "casa").unique().height == dim.height


def test_deputy_is_enriched_from_ceap_and_tse(built):
    dep = built["dim"].filter(pl.col("ideCadastro") == 62881).to_dicts()
    assert len(dep) == 1
    assert dep[0]["uf"] and dep[0]["partido"]  # vindos do CEAP via ideCadastro
    assert dep[0]["sq_candidato"] is not None  # casou com o TSE por nome + UF


def test_senators_have_names_and_no_cpf_column_anywhere(built):
    dim = built["dim"]
    names = dim.filter(pl.col("casa") == "Senado Federal")["nome_urna"].to_list()
    assert "Alan Rick" in names and all(names)
    assert not [c for c in dim.columns if "cpf" in c.lower()]


# ------------------------------- normalização isolada ------------------------------- #

def test_normalize_is_a_noop_for_the_friendly_format():
    df = pl.DataFrame({"Nome Parlamentar": ["A", "B"], "UF": ["SP", "RJ"], "Partido": ["X", "Y"], "Mandato": ["2019-2027"] * 2})
    assert normalize_senado_senadores(df).to_dicts() == df.to_dicts()


def test_normalize_dedupes_and_derives_mandate_years():
    raw = pl.read_csv(FIX / "senadores.csv", separator=";", infer_schema_length=0)
    out = normalize_senado_senadores(raw)
    assert out.height == 2 and out["Codigo Parlamentar"].n_unique() == 2
    assert out.filter(pl.col("Nome Parlamentar") == "Alan Rick")["Mandato"][0] == "2023-2031"
