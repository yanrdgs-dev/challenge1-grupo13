"""Testes unitários para o ETL de geração da tabela canônica dim_politicos (T005).

Garante estrita conformidade com o Princípio II (proibição de CPF e matching determinístico)
e Princípio X (uso de Polars/DuckDB) da Constituição.
"""

from pathlib import Path
import polars as pl
import pytest

from src.etl.build_dim_politicos import build_dim_politicos_df, EXPECTED_DIM_COLUMNS


def test_dim_politicos_schema_and_cpf_prohibition():
    """Valida o esquema de colunas obrigatórias e garante ausência estrita de CPF."""
    # Simula datasets mínimos para teste isolado
    dep_mock = pl.DataFrame({
        "uri": ["https://dadosabertos.camara.leg.br/api/v2/deputados/73485"],
        "nome": ["Pompeo de Mattos"],
        "nomeCivil": ["POMPEO MATTOS"],
        "cpf": ["12345678900"],  # Campo existente no dado bruto
        "siglaSexo": ["M"],
    })

    sen_mock = pl.DataFrame({
        "Nome Parlamentar": ["ALAN RICK"],
        "Titular/Suplente": ["Titular"],
        "UF": ["AC"],
        "Partido": ["UNIÃO"],
        "Mandato": ["2023 / 2031"],
    })

    tse_mock = pl.DataFrame({
        "SQ_CANDIDATO": [210001600000],
        "NM_CANDIDATO": ["POMPEO MATTOS"],
        "NM_URNA_CANDIDATO": ["POMPEO DE MATTOS"],
        "SG_UF": ["RS"],
        "SG_PARTIDO": ["PDT"],
        "DS_CARGO": ["DEPUTADO FEDERAL"],
        "ano": [2022],
    })

    ceap_meta_mock = pl.DataFrame({
        "ideCadastro": ["73485"],
        "txNomeParlamentar": ["Pompeo de Mattos"],
        "sgUF": ["RS"],
        "sgPartido": ["PDT"],
    })

    df_dim = build_dim_politicos_df(
        deputados_df=dep_mock,
        senadores_df=sen_mock,
        tse_candidatos_df=tse_mock,
        ceap_meta_df=ceap_meta_mock,
    )

    # 1. Valida presença de todas as colunas canônicas esperadas
    for col in EXPECTED_DIM_COLUMNS:
        assert col in df_dim.columns, f"Coluna obrigatória '{col}' ausente em dim_politicos"

    # 2. Princípio II: Proibição estrita de CPF
    assert "cpf" not in df_dim.columns
    assert "CPF" not in df_dim.columns

    # 3. Valida conteúdo gerado para deputado
    dep_row = df_dim.filter(pl.col("cargo") == "Deputado Federal").to_dicts()[0]
    assert dep_row["ideCadastro"] == 73485
    assert dep_row["nome_civil"] == "POMPEO MATTOS"
    assert dep_row["nome_urna"] == "Pompeo de Mattos"
    assert dep_row["nome_normalizado"] == "pompeo mattos"
    assert dep_row["uf"] == "RS"
    assert dep_row["partido"] == "PDT"
    assert dep_row["casa"] == "Câmara dos Deputados"

    # 4. Valida conteúdo gerado para senador
    sen_row = df_dim.filter(pl.col("cargo") == "Senador").to_dicts()[0]
    assert sen_row["nome_urna"] == "ALAN RICK"
    assert sen_row["uf"] == "AC"
    assert sen_row["partido"] == "UNIÃO"
    assert sen_row["casa"] == "Senado Federal"
    assert sen_row["ideCadastro"] is None
