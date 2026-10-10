"""Caminho de streaming do build_parquet para CSVs grandes (memória limitada, latin1 decodificado em blocos)."""

import polars as pl
import pytest

from src.etl import build_parquet
from src.etl.build_parquet import process_csv_to_parquet

NOMES = ["JOSÉ DA SILVA", "MARIA JOSÉ", "JOÃO AÇAÍ", "ZÉLIA", "ANDRÉ"]


def write_latin1_csv(path, rows=3000):
    lines = ["ANO_ELEICAO;SQ_CANDIDATO;NM_CANDIDATO;VR_PAGTO_DESPESA;DS_OBS"]
    for i in range(rows):
        ano = 2018 if i % 3 == 0 else 2022
        # a coluna DS_OBS só ganha texto depois da primeira amostra: inferência não pode quebrar
        obs = "" if i < 2000 else f"obs;{i}".replace(";", " ")
        lines.append(f"{ano};{100000 + i};{NOMES[i % len(NOMES)]};{i}.250,{i % 100:02d};{obs}")
    path.write_bytes("\n".join(lines).encode("latin1") + b"\n")


def read_all(out_dir):
    return pl.read_parquet(out_dir / "**" / "*.parquet", hive_partitioning=True).sort("SQ_CANDIDATO")


def run(tmp_path, name, **kwargs):
    csv = tmp_path / "dados_2022.csv"
    if not csv.exists():
        write_latin1_csv(csv)
    out = tmp_path / name
    summary = process_csv_to_parquet(
        csv, out, encoding="latin1", delimiter=";", partition_col="ano",
        min_reduction_pct=0.0, prune_redundant=False, **kwargs,
    )
    return summary, out


def test_streaming_output_matches_eager_output(tmp_path):
    _, eager_dir = run(tmp_path, "eager")
    _, stream_dir = run(tmp_path, "stream", large_file_bytes=1, stream_block_bytes=4096)
    eager, stream = read_all(eager_dir), read_all(stream_dir)
    assert stream.height == eager.height == 3000
    assert stream.schema == eager.schema
    assert stream.to_dicts() == eager.to_dicts()


def test_streaming_decodes_latin1_accents(tmp_path):
    _, out = run(tmp_path, "stream", large_file_bytes=1, stream_block_bytes=4096)
    nomes = set(read_all(out)["NM_CANDIDATO"].to_list())
    assert nomes == set(NOMES)


def test_streaming_converts_money_and_partitions_by_year(tmp_path):
    summary, out = run(tmp_path, "stream", large_file_bytes=1, stream_block_bytes=4096)
    df = read_all(out)
    assert df.schema["VR_PAGTO_DESPESA"] == pl.Float64
    assert df.filter(pl.col("SQ_CANDIDATO") == 100001)["VR_PAGTO_DESPESA"][0] == 1250.01
    assert summary["partitions"] == ["ano=2018", "ano=2022"]
    assert summary["rows_processed"] == 3000


def test_streaming_writes_multiple_batches_without_overwriting_files(tmp_path):
    _, out = run(tmp_path, "stream", large_file_bytes=1, stream_block_bytes=4096)
    assert len(list(out.glob("ano=2022/*.parquet"))) > 1


def test_streaming_never_loads_whole_file_with_polars_read_csv(tmp_path, monkeypatch):
    real = pl.read_csv
    sizes = []

    def spy(source, *a, **k):
        sizes.append(len(source.getvalue()) if hasattr(source, "getvalue") else -1)
        assert hasattr(source, "getvalue"), "arquivo grande não pode ir inteiro para pl.read_csv"
        return real(source, *a, **k)

    monkeypatch.setattr(build_parquet.pl, "read_csv", spy)
    run(tmp_path, "stream", large_file_bytes=1, stream_block_bytes=4096)
    assert sizes  # só a amostra passou por aqui


def test_small_files_keep_using_the_eager_path(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("streaming não devia ser usado")

    monkeypatch.setattr(build_parquet, "_stream_csv_to_partitioned_parquet", boom)
    summary, _ = run(tmp_path, "eager")
    assert summary["rows_processed"] == 3000


def test_large_file_without_partition_falls_back_to_eager(tmp_path):
    csv = tmp_path / "dados_2022.csv"
    write_latin1_csv(csv, rows=50)
    out = tmp_path / "out"
    summary = process_csv_to_parquet(
        csv, out, encoding="latin1", partition_col=None, min_reduction_pct=0.0,
        prune_redundant=False, large_file_bytes=1,
    )
    assert summary["rows_processed"] == 50


# ------------------------------- robustez dos dados reais ------------------------------- #

def test_streaming_keeps_rows_with_nul_byte_inside_a_text_field(tmp_path):
    # o TSE publica campos com byte NUL no meio do texto ("estraté\x00gica"); o pyarrow rejeita a linha
    csv = tmp_path / "dados_2022.csv"
    write_latin1_csv(csv, rows=50)
    data = csv.read_bytes().replace(b"ZELIA", b"ZE\x00LIA").replace("ZÉLIA".encode("latin1"), b"Z\xc9\x00LIA")
    csv.write_bytes(data)
    assert b"\x00" in data
    _, out = run(tmp_path, "stream", large_file_bytes=1, stream_block_bytes=4096)
    df = read_all(out)
    assert df.height == 50
    assert "ZÉLIA" in set(df["NM_CANDIDATO"].to_list())  # NUL removido, texto preservado


def test_streaming_failure_midway_leaves_no_partial_parquet(tmp_path, monkeypatch):
    real_clean = build_parquet.clean_dataframe
    calls = {"n": 0}

    def flaky(df, **kw):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("falha no terceiro bloco")
        return real_clean(df, **kw)

    monkeypatch.setattr(build_parquet, "clean_dataframe", flaky)
    with pytest.raises(RuntimeError):
        run(tmp_path, "stream", large_file_bytes=1, stream_block_bytes=4096)
    assert not list((tmp_path / "stream").rglob("*.parquet"))


def test_streaming_twice_does_not_duplicate_rows(tmp_path):
    run(tmp_path, "stream", large_file_bytes=1, stream_block_bytes=4096)
    run(tmp_path, "stream", large_file_bytes=1, stream_block_bytes=8192)  # outro nº de blocos
    assert read_all(tmp_path / "stream").height == 3000
