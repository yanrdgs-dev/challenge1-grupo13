"""build_parquet reúne vários anos de eleição na mesma tabela, particionada por ano."""

import polars as pl

from src.etl.build_parquet import process_all_datasets

COLS = ["ANO_ELEICAO", "NR_TURNO", "SG_UF", "SQ_CANDIDATO", "NM_URNA_CANDIDATO", "DS_CARGO", "QT_VOTOS_NOMINAIS"]


def write_csv(path, ano, votos):
    path.parent.mkdir(parents=True, exist_ok=True)
    row = [str(ano), "1", "SP", str(ano * 10), "FULANO", "Presidente", str(votos)]
    path.write_bytes((";".join(COLS) + "\n" + ";".join(row) + "\n").encode("latin1"))


def build(tmp_path, tabela_dir, prefixo):
    ds, out = tmp_path / "datasets", tmp_path / "out"
    for ano, votos in ((2022, 100), (2026, 200)):
        write_csv(ds / f"tse/votacao/{tabela_dir}/{prefixo}_{ano}/{prefixo}_{ano}_BRASIL.csv", ano, votos)
    process_all_datasets(datasets_dir=ds, output_base=out)
    return out


def test_munzona_of_both_years_land_in_the_same_partitioned_table(tmp_path):
    out = build(tmp_path, "munzona", "votacao_candidato_munzona")
    df = pl.read_parquet(out / "tse/votacao_munzona/**/*.parquet", hive_partitioning=True)
    assert sorted(df["ano"].unique().to_list()) == [2022, 2026]
    assert df.filter(pl.col("ano") == 2026)["QT_VOTOS_NOMINAIS"].to_list() == [200]


def test_detalhe_secao_of_both_years_land_in_a_year_agnostic_table(tmp_path):
    out = build(tmp_path, "secao", "detalhe_votacao_secao")
    df = pl.read_parquet(out / "tse/detalhe_votacao_secao/**/*.parquet", hive_partitioning=True)
    assert sorted(df["ano"].unique().to_list()) == [2022, 2026]
