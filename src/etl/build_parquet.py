"""Pipeline de ETL para ingestão de CSVs brutos e conversão para Apache Parquet via Polars."""

import argparse
import glob
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import polars as pl

from src.schemas.data_schemas import (
    DATA_SCHEMAS,
    SCHEMA_RENAMES,
    detect_schema_by_columns,
    get_schema_columns,
)

# Configuração padrão de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ETL.BuildParquet")


def clean_currency_series(series: pl.Series) -> pl.Series:
    """Higieniza e converte uma série com formato de moeda brasileiro para Float64 estrito.

    Remove separadores de milhar (ponto), substitui separador decimal (vírgula)
    por ponto e aplica cast estrito para pl.Float64.

    Args:
        series: Série do Polars com valores numéricos ou strings (ex: '1.250,50').

    Returns:
        Série convertida estritamente para pl.Float64.
    """
    if series.dtype == pl.Float64:
        return series

    # Converte para string para tratamento de pontuação
    str_col = (
        series.cast(pl.Utf8)
        .str.strip_chars()
        .str.replace_all(r"\.", "")
        .str.replace(",", ".")
    )

    # Substitui strings vazias ou nulas por None antes do cast estrito
    clean_expr = (
        pl.when(str_col.is_null() | (str_col == "") | (str_col == "None"))
        .then(None)
        .otherwise(str_col)
        .cast(pl.Float64, strict=True)
    )

    return pl.select(clean_expr.alias(series.name)).to_series()


def clean_dataframe(
    df: pl.DataFrame,
    partition_col: str = "ano",
    selected_columns: Optional[List[str]] = None,
    schema_name: Optional[str] = None,
    prune_redundant: bool = True,
) -> pl.DataFrame:
    """Aplica higienização, tipagem estrita, normalização e poda de colunas redundantes.

    Atende aos critérios das Tasks 1.1 e 1.2:
    - Converte VR_PAGTO_DESPESA de string com vírgula para Float64 estrito.
    - Converte outras colunas financeiras (prefixo VR_ ou vlr).
    - Garante a existência da coluna de partição de ano (mapeando de ANO_ELEICAO se necessário).
    - Poda de colunas redundantes e projeção de atributos conforme schema formal.

    Args:
        df: DataFrame bruto lido do CSV.
        partition_col: Nome da coluna que será utilizada para particionamento físico.
        selected_columns: Lista explícita de colunas a serem mantidas no Parquet final.
        schema_name: Nome do schema predefinido (ex: 'tse_candidatos', 'tse_despesas').
        prune_redundant: Se True, ativa a poda automática de colunas caso o schema seja identificado.

    Returns:
        DataFrame tratado, tipado e podado.
    """
    expressions = []

    # 1. Tratamento específico e estrito de VR_PAGTO_DESPESA
    if "VR_PAGTO_DESPESA" in df.columns:
        col_clean = (
            pl.col("VR_PAGTO_DESPESA")
            .cast(pl.Utf8)
            .str.strip_chars()
            .str.replace_all(r"\.", "")
            .str.replace(",", ".")
        )
        expr_vr = (
            pl.when(col_clean.is_null() | (col_clean == "") | (col_clean == "None"))
            .then(None)
            .otherwise(col_clean)
            .cast(pl.Float64, strict=True)
            .alias("VR_PAGTO_DESPESA")
        )
        expressions.append(expr_vr)

    # 2. Tratamento de outras colunas financeiras comuns (ex: VR_BEM_CANDIDATO, vlrLiquido, etc.)
    for col_name in df.columns:
        if (col_name.startswith("VR_") or col_name.startswith("vlr")) and col_name != "VR_PAGTO_DESPESA":
            col_str = (
                pl.col(col_name)
                .cast(pl.Utf8)
                .str.strip_chars()
                .str.replace_all(r"\.", "")
                .str.replace(",", ".")
            )
            expressions.append(
                pl.when(col_str.is_null() | (col_str == "") | (col_str == "None"))
                .then(None)
                .otherwise(col_str)
                .cast(pl.Float64, strict=False)
                .alias(col_name)
            )

    # 3. Normalização da coluna de partição por ano
    if partition_col == "ano" and "ano" not in df.columns:
        if "ANO_ELEICAO" in df.columns:
            expressions.append(
                pl.col("ANO_ELEICAO").cast(pl.Int32).alias("ano")
            )
        elif "ano_eleicao" in df.columns:
            expressions.append(
                pl.col("ano_eleicao").cast(pl.Int32).alias("ano")
            )
        elif "numAno" in df.columns:
            expressions.append(
                pl.col("numAno").cast(pl.Int32).alias("ano")
            )
        elif "dataHoraVoto" in df.columns:
            expressions.append(
                pl.col("dataHoraVoto").cast(pl.Utf8).str.slice(0, 4).cast(pl.Int32).alias("ano")
            )

    if expressions:
        df = df.with_columns(expressions)

    # 4. Poda Estrutural (Pruning) e Filtro de Colunas por Schema (Task 1.1 e 1.2)
    target_columns: Optional[List[str]] = None
    target_schema_key: Optional[str] = None

    if selected_columns:
        target_columns = list(selected_columns)
    elif schema_name and schema_name.lower() not in ("none", "auto"):
        target_columns = get_schema_columns(schema_name)
        target_schema_key = schema_name.lower()
    elif prune_redundant:
        detected = detect_schema_by_columns(df.columns)
        if detected:
            target_columns = get_schema_columns(detected)
            target_schema_key = detected
            logger.info("Schema detectado automaticamente para poda: '%s'", detected)

    if target_columns:
        # Mantém apenas colunas presentes no DataFrame que pertencem ao schema
        cols_to_keep = [col for col in target_columns if col in df.columns]

        # Garante que a coluna de partição seja sempre preservada
        if partition_col in df.columns and partition_col not in cols_to_keep:
            cols_to_keep.append(partition_col)

        orig_count = len(df.columns)
        df = df.select(cols_to_keep)
        pruned_count = orig_count - len(cols_to_keep)
        logger.info(
            "Poda de colunas aplicada: %d mantidas, %d redundantes eliminadas (%d -> %d).",
            len(cols_to_keep),
            pruned_count,
            orig_count,
            len(cols_to_keep),
        )

        # Aplica padronização / renomeação de colunas brutas para nomes canônicos se configurado
        if target_schema_key and target_schema_key in SCHEMA_RENAMES:
            rename_map = {
                old: new
                for old, new in SCHEMA_RENAMES[target_schema_key].items()
                if old in df.columns and new not in df.columns
            }
            if rename_map:
                logger.info("Normalizando colunas canônicas: %s", rename_map)
                df = df.rename(rename_map)

    return df


def find_csv_files(input_path: Union[str, Path]) -> List[Path]:
    """Localiza todos os arquivos CSV a partir do caminho informado."""
    path = Path(input_path)
    if path.is_file():
        if path.suffix.lower() == ".csv":
            return [path]
        return []
    elif path.is_dir():
        files = sorted(list(path.glob("*.csv")) + list(path.glob("**/*.csv")))
        # Remove duplicatas preservando ordem
        seen = set()
        unique_files = []
        for f in files:
            if f.resolve() not in seen:
                seen.add(f.resolve())
                unique_files.append(f)
        return unique_files
    return []


def process_csv_to_parquet(
    input_path: Union[str, Path],
    output_dir: Union[str, Path],
    encoding: str = "latin1",
    delimiter: str = ";",
    compression: str = "zstd",
    compression_level: int = 3,
    partition_col: str = "ano",
    min_reduction_pct: float = 70.0,
    selected_columns: Optional[List[str]] = None,
    schema_name: Optional[str] = None,
    prune_redundant: bool = True,
) -> Dict[str, Any]:
    """Executa o pipeline completo de ingestão, tratamento e serialização em Parquet particionado.

    Args:
        input_path: Arquivo CSV individual ou diretório contendo CSVs brutos.
        output_dir: Diretório de destino onde os arquivos Parquet serão gravados.
        encoding: Codificação dos arquivos CSV (padrão 'latin1').
        delimiter: Delimitador de colunas do CSV (padrão ';').
        compression: Algoritmo de compressão do Parquet (padrão 'zstd').
        compression_level: Nível de compressão zstd (padrão 3).
        partition_col: Nome da coluna para particionamento físico (ex: 'ano').
        min_reduction_pct: Percentual mínimo exigido de redução de tamanho (padrão 70.0%).
        selected_columns: Lista de colunas para filtragem explícita.
        schema_name: Nome do schema para poda estrutural (Task 1.1).
        prune_redundant: Se True, aplica a poda de colunas redundantes.

    Returns:
        Dicionário com sumário e estatísticas da execução.
    """
    input_files = find_csv_files(input_path)
    if not input_files:
        raise FileNotFoundError(
            f"Nenhum arquivo CSV encontrado no caminho especificado: '{input_path}'"
        )

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    logger.info("Iniciando ingestão de %d arquivo(s) CSV...", len(input_files))

    total_csv_bytes = 0
    dfs: List[pl.DataFrame] = []

    for file_path in input_files:
        file_size = file_path.stat().st_size
        total_csv_bytes += file_size
        logger.info(
            "Lendo '%s' (tamanho: %.2f KB, encoding: %s, sep: '%s')",
            file_path.name,
            file_size / 1024,
            encoding,
            delimiter,
        )

        df_file = pl.read_csv(
            file_path,
            separator=delimiter,
            encoding=encoding,
            infer_schema_length=10000,
            ignore_errors=False,
        )
        dfs.append(df_file)

    # Concatena todos os dataframes ingeridos
    if len(dfs) == 1:
        full_df = dfs[0]
    else:
        full_df = pl.concat(dfs, how="diagonal_relaxed")

    total_rows = full_df.height
    total_cols_before = len(full_df.columns)
    logger.info("Total de registros ingeridos: %d | Colunas brutas: %d", total_rows, total_cols_before)

    # Aplica sanitização, cast de tipos e poda estrutural
    logger.info("Aplicando sanitização, cast estrito e poda de colunas...")
    cleaned_df = clean_dataframe(
        full_df,
        partition_col=partition_col,
        selected_columns=selected_columns,
        schema_name=schema_name,
        prune_redundant=prune_redundant,
    )
    total_cols_after = len(cleaned_df.columns)

    if "VR_PAGTO_DESPESA" in cleaned_df.columns:
        actual_dtype = cleaned_df.schema["VR_PAGTO_DESPESA"]
        if actual_dtype != pl.Float64:
            raise TypeError(
                f"Erro no critério de aceite: VR_PAGTO_DESPESA possui tipo {actual_dtype}, "
                f"esperava Float64."
            )
        logger.info("✓ VR_PAGTO_DESPESA convertido com sucesso para Float64.")

    # Verifica coluna de partição
    if partition_col not in cleaned_df.columns:
        raise ValueError(
            f"Coluna de partição '{partition_col}' não encontrada no DataFrame tratado. "
            f"Colunas disponíveis: {cleaned_df.columns}"
        )

    logger.info(
        "Gravando Parquet particionado por '%s' em '%s' (compressão: %s, nível: %d)...",
        partition_col,
        out_path,
        compression,
        compression_level,
    )

    # Gravação nativa do Parquet particionado no Polars com compressão zstd
    cleaned_df.write_parquet(
        out_path,
        partition_by=partition_col,
        compression=compression,
        compression_level=compression_level,
        mkdir=True,
    )

    # Calcula o tamanho total dos arquivos Parquet gerados
    parquet_files = list(out_path.glob(f"**/*.parquet"))
    total_parquet_bytes = sum(f.stat().st_size for f in parquet_files)

    if total_csv_bytes > 0:
        reduction_pct = (1.0 - (total_parquet_bytes / total_csv_bytes)) * 100.0
    else:
        reduction_pct = 0.0

    partitions = sorted(list({p.parent.name for p in parquet_files}))
    meets_target = reduction_pct >= min_reduction_pct

    summary = {
        "rows_processed": total_rows,
        "input_files_count": len(input_files),
        "columns_before": total_cols_before,
        "columns_after": total_cols_after,
        "pruned_columns_count": total_cols_before - total_cols_after,
        "csv_bytes": total_csv_bytes,
        "csv_size_kb": round(total_csv_bytes / 1024, 2),
        "parquet_bytes": total_parquet_bytes,
        "parquet_size_kb": round(total_parquet_bytes / 1024, 2),
        "reduction_pct": round(reduction_pct, 2),
        "partitions": partitions,
        "parquet_files_count": len(parquet_files),
        "output_dir": str(out_path.resolve()),
        "meets_target": meets_target,
    }

    logger.info("==================================================")
    logger.info("              SUMÁRIO DO PIPELINE ETL             ")
    logger.info("==================================================")
    logger.info("Linhas processadas:      %d", total_rows)
    logger.info("Colunas antes / depois:  %d -> %d (Poda: -%d colunas)", total_cols_before, total_cols_after, summary["pruned_columns_count"])
    logger.info("Tamanho CSV bruto:       %.2f KB", summary["csv_size_kb"])
    logger.info("Tamanho Parquet final:   %.2f KB", summary["parquet_size_kb"])
    logger.info("Redução volumétrica:     %.2f%%", summary["reduction_pct"])
    logger.info("Partições geradas:       %s", partitions)

    if meets_target:
        logger.info(
            "✓ Redução superior ou igual a %.1f%% (Critério de Aceite: Aprovado)",
            min_reduction_pct,
        )
    else:
        logger.warning(
            "⚠ AVISO: Redução de %.2f%% inferior à meta de %.1f%%",
            summary["reduction_pct"],
            min_reduction_pct,
        )

    return summary


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Configura e analisa argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        description="Pipeline ETL: Ingestão de CSVs e conversão para Apache Parquet via Polars."
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_path",
        default="data/raw",
        help="Caminho para arquivo CSV ou diretório com CSVs brutos (padrão: data/raw).",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output_dir",
        default="data/processed/despesas",
        help="Diretório de destino para gravação dos Parquets particionados (padrão: data/processed/despesas).",
    )
    parser.add_argument(
        "-e",
        "--encoding",
        default="latin1",
        help="Codificação dos arquivos CSV (padrão: latin1).",
    )
    parser.add_argument(
        "-d",
        "--delimiter",
        default=";",
        help="Delimitador do CSV (padrão: ';').",
    )
    parser.add_argument(
        "-c",
        "--compression",
        default="zstd",
        choices=["zstd", "snappy", "gzip", "lz4", "uncompressed"],
        help="Algoritmo de compressão do Parquet (padrão: zstd).",
    )
    parser.add_argument(
        "--compression-level",
        type=int,
        default=3,
        help="Nível de compressão zstd (padrão: 3).",
    )
    parser.add_argument(
        "-p",
        "--partition-col",
        default="ano",
        help="Coluna para particionamento físico dos diretórios (padrão: 'ano').",
    )
    parser.add_argument(
        "--min-reduction",
        type=float,
        default=70.0,
        help="Percentual mínimo de redução exigido (padrão: 70.0).",
    )
    parser.add_argument(
        "-s",
        "--schema",
        dest="schema_name",
        default="auto",
        choices=["auto", "tse_despesas", "tse_candidatos", "tse_bens", "camara_votacoes", "camara_ceap", "none"],
        help="Nome do schema para poda estrutural (Task 1.1) (padrão: auto).",
    )
    parser.add_argument(
        "--columns",
        dest="columns",
        default=None,
        help="Lista de colunas específicas separadas por vírgula para seleção manual.",
    )
    parser.add_argument(
        "--no-prune",
        dest="no_prune",
        action="store_true",
        help="Desativa a poda de colunas redundantes, mantendo todas as colunas brutas.",
    )
    return parser.parse_args(args)


def main() -> None:
    """Ponto de entrada CLI do pipeline de ETL."""
    args = parse_args()
    try:
        selected_cols = [c.strip() for c in args.columns.split(",")] if args.columns else None
        prune_redundant = not args.no_prune

        summary = process_csv_to_parquet(
            input_path=args.input_path,
            output_dir=args.output_dir,
            encoding=args.encoding,
            delimiter=args.delimiter,
            compression=args.compression,
            compression_level=args.compression_level,
            partition_col=args.partition_col,
            min_reduction_pct=args.min_reduction,
            selected_columns=selected_cols,
            schema_name=args.schema_name,
            prune_redundant=prune_redundant,
        )
        if not summary["meets_target"]:
            logger.warning("Pipeline finalizou com redução abaixo da meta.")
        sys.exit(0)
    except Exception as e:
        logger.error("Erro na execução do pipeline ETL: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
