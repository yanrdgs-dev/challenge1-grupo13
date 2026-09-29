"""Testes automatizados para o pipeline de ETL e conversão para Parquet (Task 1.2)."""

import os
import subprocess
import sys
from pathlib import Path
import polars as pl
import pyarrow.parquet as pq
import pytest

from src.etl.build_parquet import (
    clean_currency_series,
    clean_dataframe,
    process_csv_to_parquet,
)


def test_clean_currency_series_various_formats():
    """Valida conversão e cast estrito de valores monetários para Float64."""
    input_values = [
        "1.250,50",
        "25,00",
        "0,00",
        "-120,75",
        "1000000,99",
        "1.000.000,99",
        "",
        " ",
        None,
    ]
    series = pl.Series("VR_PAGTO_DESPESA", input_values)
    result = clean_currency_series(series)

    assert result.dtype == pl.Float64
    expected = [
        1250.50,
        25.00,
        0.00,
        -120.75,
        1000000.99,
        1000000.99,
        None,
        None,
        None,
    ]
    assert result.to_list() == expected


def test_clean_dataframe_strict_cast_and_year_mapping():
    """Valida que o DataFrame resultante tem VR_PAGTO_DESPESA como Float64 e partição de ano."""
    df = pl.DataFrame({
        "ANO_ELEICAO": [2024, 2020],
        "NM_CANDIDATO": ["CANDIDATO A", "CANDIDATO B"],
        "VR_PAGTO_DESPESA": ["1.500,00", "300,50"],
    })

    cleaned = clean_dataframe(df, partition_col="ano")

    assert cleaned.schema["VR_PAGTO_DESPESA"] == pl.Float64
    assert cleaned.schema["ano"] == pl.Int32
    assert cleaned["VR_PAGTO_DESPESA"].to_list() == [1500.0, 300.50]
    assert cleaned["ano"].to_list() == [2024, 2020]


def test_process_csv_latin1_and_partitioning(tmp_path):
    """Testa leitura de CSV com codificação latin1 e particionamento físico por ano."""
    csv_content = (
        "ANO_ELEICAO;NM_CANDIDATO;DS_CARGO;VR_PAGTO_DESPESA\n"
        "2024;JOÃO ELEIÇÃO;PREFEITO;5.000,50\n"
        "2024;MARIA JOSÉ;VEREADOR;1.200,00\n"
        "2020;AÇÃO CIDADÃ;PREFEITO;850,25\n"
    ).encode("latin1")

    input_csv = tmp_path / "raw_despesas.csv"
    input_csv.write_bytes(csv_content)

    output_dir = tmp_path / "processed" / "despesas"

    summary = process_csv_to_parquet(
        input_path=input_csv,
        output_dir=output_dir,
        encoding="latin1",
        delimiter=";",
        compression="zstd",
        partition_col="ano",
    )

    assert summary["rows_processed"] == 3
    assert set(summary["partitions"]) == {"ano=2020", "ano=2024"}

    # Verifica os arquivos parquet gerados
    parquet_2024 = list((output_dir / "ano=2024").glob("*.parquet"))
    assert len(parquet_2024) >= 1

    df_2024 = pl.read_parquet(parquet_2024[0])
    assert df_2024.schema["VR_PAGTO_DESPESA"] == pl.Float64
    assert "JOÃO ELEIÇÃO" in df_2024["NM_CANDIDATO"].to_list()
    assert df_2024["VR_PAGTO_DESPESA"].to_list() == [5000.50, 1200.00]


def test_compression_zstd_and_70_percent_reduction(tmp_path):
    """Valida que a compressão zstd atinge pelo menos 70% de redução volumétrica."""
    rows = 4000
    lines = ["ANO_ELEICAO;SG_UF;NM_CANDIDATO;DS_CARGO;VR_PAGTO_DESPESA"]
    for i in range(rows):
        ano = 2024 if i % 2 == 0 else 2020
        uf = "SP" if i % 3 == 0 else "RJ"
        nome = f"CANDIDATO DE TESTE NÚMERO {i % 40} DA SILVA"
        cargo = "VEREADOR MUNICIPAL" if i % 2 == 0 else "PREFEITO"
        valor = f"{(i * 17.85):.2f}".replace(".", ",")
        lines.append(f"{ano};{uf};{nome};{cargo};{valor}")

    csv_text = "\n".join(lines).encode("latin1")
    input_csv = tmp_path / "large_despesas.csv"
    input_csv.write_bytes(csv_text)

    output_dir = tmp_path / "processed_large"

    summary = process_csv_to_parquet(
        input_path=input_csv,
        output_dir=output_dir,
        encoding="latin1",
        delimiter=";",
        compression="zstd",
        partition_col="ano",
        min_reduction_pct=70.0,
    )

    # Verifica taxa de redução
    assert summary["reduction_pct"] >= 70.0
    assert summary["meets_target"] is True

    # Verifica se os metadados do Parquet comprovam compressão ZSTD
    parquet_file = list(output_dir.glob("**/*.parquet"))[0]
    parquet_meta = pq.read_metadata(str(parquet_file))
    first_col_chunk = parquet_meta.row_group(0).column(0)
    assert first_col_chunk.compression.upper() == "ZSTD"


def test_cli_execution_standalone(tmp_path):
    """Valida a execução do pipeline via linha de comando."""
    csv_content = (
        "ANO_ELEICAO;NM_CANDIDATO;VR_PAGTO_DESPESA\n"
        "2024;TESTE CLI;99,90\n"
    ).encode("latin1")

    input_dir = tmp_path / "raw"
    input_dir.mkdir()
    (input_dir / "cli_test.csv").write_bytes(csv_content)

    output_dir = tmp_path / "processed_cli"

    cmd = [
        sys.executable,
        "-m",
        "src.etl.build_parquet",
        "--input",
        str(input_dir),
        "--output",
        str(output_dir),
        "--encoding",
        "latin1",
        "--delimiter",
        ";",
        "--compression",
        "zstd",
        "--min-reduction",
        "0.0",  # Para lote minúsculo não falhar por overhead de header
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0
    assert "SUMÁRIO DO PIPELINE ETL" in result.stderr or "SUMÁRIO DO PIPELINE ETL" in result.stdout
    assert (output_dir / "ano=2024").exists()


def test_missing_csv_raises_file_not_found(tmp_path):
    """Valida lançamento de FileNotFoundError quando não há CSVs."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    with pytest.raises(FileNotFoundError):
        process_csv_to_parquet(
            input_path=empty_dir,
            output_dir=tmp_path / "out",
        )


def test_schema_pruning_tse_candidatos():
    """Valida que clean_dataframe poda colunas burocráticas/redundantes mantendo o schema do MVP."""
    raw_data = {
        "DT_GERACAO": ["22/09/2026"],
        "HH_GERACAO": ["08:31:23"],
        "ANO_ELEICAO": [2026],
        "CD_TIPO_ELEICAO": [2],
        "SG_UF": ["SP"],
        "SQ_CANDIDATO": [250001],
        "NM_CANDIDATO": ["MARCIO ALVES DOS SANTOS"],
        "NM_URNA_CANDIDATO": ["MARCIO ALVES"],
        "SG_PARTIDO": ["UP"],
        "DS_CARGO": ["SENADOR"],
        "CD_CARGO": [5],
        "NR_TITULO_ELEITORAL_CANDIDATO": ["123456789"],
        "CD_COR_RACA": ["02"],
    }
    df = pl.DataFrame(raw_data)
    assert len(df.columns) == 13

    # Com poda automática por schema detectado
    cleaned = clean_dataframe(df, partition_col="ano", prune_redundant=True)

    # Verifica que colunas burocráticas foram podadas
    assert "DT_GERACAO" not in cleaned.columns
    assert "HH_GERACAO" not in cleaned.columns
    assert "CD_TIPO_ELEICAO" not in cleaned.columns
    assert "NR_TITULO_ELEITORAL_CANDIDATO" not in cleaned.columns

    # Verifica que atributos oficiais da Task 1.1 e partição foram preservados
    assert "ANO_ELEICAO" in cleaned.columns
    assert "SG_UF" in cleaned.columns
    assert "SQ_CANDIDATO" in cleaned.columns
    assert "NM_CANDIDATO" in cleaned.columns
    assert "NM_URNA_CANDIDATO" in cleaned.columns
    assert "SG_PARTIDO" in cleaned.columns
    assert "DS_CARGO" in cleaned.columns
    assert "ano" in cleaned.columns
    assert len(cleaned.columns) == 8


def test_explicit_selected_columns_filter(tmp_path):
    """Valida o filtro explícito de colunas selecionadas no pipeline."""
    csv_content = (
        "ANO_ELEICAO;SG_UF;NM_CANDIDATO;DS_CARGO;COLUNA_DESNECESSARIA;VR_PAGTO_DESPESA\n"
        "2026;SP;CANDIDATO X;GOVERNADOR;LIXO;1000,00\n"
    ).encode("latin1")

    input_csv = tmp_path / "raw.csv"
    input_csv.write_bytes(csv_content)
    output_dir = tmp_path / "out"

    selected = ["ANO_ELEICAO", "NM_CANDIDATO", "VR_PAGTO_DESPESA"]
    summary = process_csv_to_parquet(
        input_path=input_csv,
        output_dir=output_dir,
        selected_columns=selected,
        partition_col="ano",
        min_reduction_pct=0.0,
    )

    assert summary["columns_before"] == 6
    assert summary["columns_after"] == 4  # 3 selecionadas + partição 'ano'
    assert summary["pruned_columns_count"] == 2

    parquet_file = list(output_dir.glob("**/*.parquet"))[0]
    df = pl.read_parquet(parquet_file)
    assert set(df.columns) == {"ANO_ELEICAO", "NM_CANDIDATO", "VR_PAGTO_DESPESA", "ano"}


def test_cli_execution_with_schema_flag(tmp_path):
    """Valida execução da CLI especificando o schema para poda de colunas."""
    csv_content = (
        "ANO_ELEICAO;SG_UF;SQ_CANDIDATO;DS_TIPO_BEM_CANDIDATO;DS_BEM_CANDIDATO;VR_BEM_CANDIDATO;COLUNA_EXTRA\n"
        "2026;SP;12345;VEICULO;CARRO;50000,00;DADO_DESCARTAVEL\n"
    ).encode("latin1")

    input_dir = tmp_path / "raw"
    input_dir.mkdir()
    (input_dir / "bens.csv").write_bytes(csv_content)
    output_dir = tmp_path / "out_bens"

    cmd = [
        sys.executable,
        "-m",
        "src.etl.build_parquet",
        "--input",
        str(input_dir),
        "--output",
        str(output_dir),
        "--schema",
        "tse_bens",
        "--min-reduction",
        "0.0",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0

    parquet_file = list(output_dir.glob("**/*.parquet"))[0]
    df = pl.read_parquet(parquet_file)
    assert "COLUNA_EXTRA" not in df.columns
    assert "VR_BEM_CANDIDATO" in df.columns
    assert df.schema["VR_BEM_CANDIDATO"] == pl.Float64

