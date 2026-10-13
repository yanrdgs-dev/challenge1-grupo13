"""O catálogo em memória acompanha o dim_politicos.parquet quando a ingestão publica uma versão nova."""

import os

import polars as pl
import pytest

from src.tools.politician_cache import PoliticianCache
from src.tools.resolve_politician import resolve_politician


def write_dim(path, nomes):
    pl.DataFrame({
        "sq_candidato": [None] * len(nomes), "ideCadastro": list(range(1, len(nomes) + 1)), "cod_senador": [None] * len(nomes),
        "nome_civil": [n.upper() for n in nomes], "nome_urna": nomes, "nome_normalizado": [n.lower() for n in nomes],
        "casa": ["Câmara dos Deputados"] * len(nomes), "cargo": ["Deputado Federal"] * len(nomes),
        "uf": ["SP"] * len(nomes), "partido": ["X"] * len(nomes), "mandato_anos": ["2023-2027"] * len(nomes),
    }, schema_overrides={"sq_candidato": pl.Int64, "cod_senador": pl.Int64}).write_parquet(path)


@pytest.fixture(autouse=True)
def fresh_singleton():
    PoliticianCache.reset()
    yield
    PoliticianCache.reset()


def bump_mtime(path, seconds=10):
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + seconds * 1_000_000_000))


def test_new_version_of_the_parquet_is_picked_up_without_restart(tmp_path):
    p = tmp_path / "dim.parquet"
    write_dim(p, ["Ana Souza"])
    assert [r["nome_urna"] for r in PoliticianCache.get_instance(str(p)).records] == ["Ana Souza"]
    tmp = tmp_path / "dim.new"
    write_dim(tmp, ["Ana Souza", "Bruno Lima"])
    os.replace(tmp, p)  # é assim que a publicação da ingestão troca o arquivo
    bump_mtime(p)
    cache = PoliticianCache.get_instance(str(p))
    assert sorted(r["nome_urna"] for r in cache.records) == ["Ana Souza", "Bruno Lima"]
    assert "bruno lima" in cache.urna_index or any("bruno" in k for k in cache.urna_index)


def test_unchanged_parquet_is_not_reloaded(tmp_path, monkeypatch):
    p = tmp_path / "dim.parquet"
    write_dim(p, ["Ana Souza"])
    cache = PoliticianCache.get_instance(str(p))
    loads = []
    real = cache.load_from_dataframe
    monkeypatch.setattr(cache, "load_from_dataframe", lambda df: loads.append(1) or real(df))
    for _ in range(5):
        PoliticianCache.get_instance(str(p))
    assert loads == []


def test_parquet_replaced_by_a_corrupt_file_keeps_the_previous_catalog(tmp_path):
    p = tmp_path / "dim.parquet"
    write_dim(p, ["Ana Souza"])
    PoliticianCache.get_instance(str(p))
    p.write_bytes(b"isto nao e parquet")
    bump_mtime(p)
    cache = PoliticianCache.get_instance(str(p))
    assert [r["nome_urna"] for r in cache.records] == ["Ana Souza"]


def test_parquet_removed_keeps_the_previous_catalog(tmp_path):
    p = tmp_path / "dim.parquet"
    write_dim(p, ["Ana Souza"])
    PoliticianCache.get_instance(str(p))
    p.unlink()
    assert len(PoliticianCache.get_instance(str(p)).records) == 1


def test_resolve_politician_sees_the_new_catalog(tmp_path):
    p = tmp_path / "dim.parquet"
    write_dim(p, ["Ana Souza"])
    assert "Bruno Lima" not in str(resolve_politician("Bruno Lima", uf="SP", parquet_path=str(p)))
    write_dim(p, ["Ana Souza", "Bruno Lima"])
    bump_mtime(p)
    out = resolve_politician("Bruno Lima", uf="SP", parquet_path=str(p))
    assert "Bruno Lima" in str(out)
