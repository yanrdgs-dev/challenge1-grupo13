"""Pipeline de ETL para ingestão de CSVs brutos e conversão para Apache Parquet via Polars."""

import argparse
import glob
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import polars as pl

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
    partition_col: Optional[str] = "ano",
) -> pl.DataFrame:
    """Aplica higienização, tipagem estrita e normalização de colunas no DataFrame.

    - Converte VR_PAGTO_DESPESA de string com vírgula para Float64 estrito.
    - Converte outras colunas de valor monetário (prefixo VR_, vlr, VALOR_) se presentes.
    - Garante a existência da coluna de partição de ano (mapeando de ANO_ELEICAO, numAno, ANO, etc.).

    Args:
        df: DataFrame bruto lido do CSV.
        partition_col: Nome da coluna que será utilizada para particionamento físico.

    Returns:
        DataFrame tratado e tipado.
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

    # 2. Tratamento de outras colunas financeiras comuns do TSE, Câmara e Senado
    currency_cols = {
        "vlrLiquido", "vlrDocumento", "vlrGlosa", "vlrRestituicao",
        "VALOR_REEMBOLSADO", "VR_BEM_CANDIDATO", "VR_RECEITA",
        "VR_DESPESA_CONTRATADA",
    }
    for col_name in df.columns:
        is_currency = (
            (
                col_name.startswith("VR_")
                or col_name.startswith("vlr")
                or col_name.startswith("VALOR_")
                or col_name.endswith("_VALOR")
                or col_name in currency_cols
            )
            and col_name != "VR_PAGTO_DESPESA"
        )
        if is_currency:
            col_raw = pl.col(col_name).cast(pl.Utf8).str.strip_chars()
            col_str = (
                pl.when(col_raw.str.contains(","))
                .then(col_raw.str.replace_all(r"\.", "").str.replace(",", "."))
                .otherwise(col_raw)
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
                pl.col("ANO_ELEICAO").cast(pl.Int32, strict=False).alias("ano")
            )
        elif "ano_eleicao" in df.columns:
            expressions.append(
                pl.col("ano_eleicao").cast(pl.Int32, strict=False).alias("ano")
            )
        elif "numAno" in df.columns:
            expressions.append(
                pl.col("numAno").cast(pl.Int32, strict=False).alias("ano")
            )
        elif "ANO" in df.columns:
            expressions.append(
                pl.col("ANO").cast(pl.Int32, strict=False).alias("ano")
            )
        elif "Ano" in df.columns:
            expressions.append(
                pl.col("Ano").cast(pl.Int32, strict=False).alias("ano")
            )
    elif partition_col == "ano" and "ano" in df.columns:
        if df.schema["ano"] != pl.Int32:
            expressions.append(
                pl.col("ano").cast(pl.Int32, strict=False).alias("ano")
            )

    if expressions:
        df = df.with_columns(expressions)

    return df


def find_csv_files(
    input_path: Union[str, Path],
    prefer_brasil: bool = False,
    filter_pattern: Optional[str] = None,
) -> List[Path]:
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

        if filter_pattern:
            unique_files = [f for f in unique_files if filter_pattern in f.name]

        if prefer_brasil:
            brasil_files = [f for f in unique_files if "_BRASIL.csv" in f.name]
            if brasil_files:
                return brasil_files
        return unique_files
    return []


def process_csv_to_parquet(
    input_path: Union[str, Path],
    output_dir: Union[str, Path],
    encoding: str = "latin1",
    delimiter: str = ";",
    compression: str = "zstd",
    compression_level: int = 3,
    partition_col: Optional[str] = "ano",
    min_reduction_pct: float = 70.0,
    prefer_brasil: bool = False,
    filter_pattern: Optional[str] = None,
) -> Dict[str, Any]:
    """Executa o pipeline completo de ingestão, tratamento e serialização em Parquet.

    Args:
        input_path: Arquivo CSV individual ou diretório contendo CSVs brutos.
        output_dir: Diretório de destino onde os arquivos Parquet serão gravados.
        encoding: Codificação dos arquivos CSV (padrão 'latin1').
        delimiter: Delimitador de colunas do CSV (padrão ';').
        compression: Algoritmo de compressão do Parquet (padrão 'zstd').
        compression_level: Nível de compressão zstd (padrão 3).
        partition_col: Nome da coluna para particionamento físico (ex: 'ano' ou None).
        min_reduction_pct: Percentual mínimo exigido de redução de tamanho (padrão 70.0%).
        prefer_brasil: Se True, filtra apenas arquivos com sufixo _BRASIL.csv quando disponíveis.
        filter_pattern: Padrão textual opcional para filtrar nomes de arquivos CSV.

    Returns:
        Dicionário com sumário e estatísticas da execução.
    """
    input_files = find_csv_files(input_path, prefer_brasil=prefer_brasil, filter_pattern=filter_pattern)
    if not input_files:
        raise FileNotFoundError(
            f"Nenhum arquivo CSV encontrado no caminho especificado: '{input_path}' (filtro: {filter_pattern})"
        )

    out_path = Path(output_dir)
    if str(partition_col).lower() in ("none", ""):
        partition_col = None

    if partition_col or not str(output_dir).endswith(".parquet"):
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

        try:
            df_file = pl.read_csv(
                file_path,
                separator=delimiter,
                encoding=encoding,
                infer_schema_length=10000,
                ignore_errors=True,
                truncate_ragged_lines=True,
            )
        except Exception:
            alt_enc = "utf8-lossy" if encoding == "latin1" else "latin1"
            df_file = pl.read_csv(
                file_path,
                separator=delimiter,
                encoding=alt_enc,
                infer_schema_length=10000,
                ignore_errors=True,
                truncate_ragged_lines=True,
            )

        # Se partition_col == "ano" e ainda não tem ano na tabela nem nas colunas mapeadas, tenta extrair do nome do arquivo
        if partition_col == "ano" and "ano" not in df_file.columns:
            has_candidate = any(
                c in df_file.columns for c in ("ANO_ELEICAO", "ano_eleicao", "numAno", "ANO", "Ano")
            )
            if not has_candidate:
                match = re.search(r"(?:19|20)\d{2}", file_path.stem)
                if match:
                    df_file = df_file.with_columns(
                        pl.lit(int(match.group(0))).cast(pl.Int32).alias("ano")
                    )

        dfs.append(df_file)

    # Concatena todos os dataframes ingeridos
    if len(dfs) == 1:
        full_df = dfs[0]
    else:
        full_df = pl.concat(dfs, how="diagonal_relaxed")

    total_rows = full_df.height
    logger.info("Total de registros ingeridos: %d", total_rows)

    # Aplica sanitização e cast de tipos
    logger.info("Aplicando sanitização e tipagem...")
    cleaned_df = clean_dataframe(full_df, partition_col=partition_col)

    if "VR_PAGTO_DESPESA" in cleaned_df.columns:
        actual_dtype = cleaned_df.schema["VR_PAGTO_DESPESA"]
        if actual_dtype != pl.Float64:
            raise TypeError(
                f"Erro no critério de aceite: VR_PAGTO_DESPESA possui tipo {actual_dtype}, "
                f"esperava Float64."
            )
        logger.info("✓ VR_PAGTO_DESPESA convertido com sucesso para Float64.")

    # Gravação do Parquet
    if partition_col:
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
        cleaned_df.write_parquet(
            out_path,
            partition_by=partition_col,
            compression=compression,
            compression_level=compression_level,
            mkdir=True,
        )
    else:
        logger.info(
            "Gravando Parquet direto em '%s' (compressão: %s, nível: %d)...",
            out_path,
            compression,
            compression_level,
        )
        if str(output_dir).endswith(".parquet"):
            target_file = out_path
            target_file.parent.mkdir(parents=True, exist_ok=True)
        else:
            out_path.mkdir(parents=True, exist_ok=True)
            stem_name = Path(input_path).stem if Path(input_path).is_file() else "data"
            target_file = out_path / f"{stem_name}.parquet"

        cleaned_df.write_parquet(
            target_file,
            compression=compression,
            compression_level=compression_level,
        )

    # Calcula o tamanho total dos arquivos Parquet gerados
    if str(output_dir).endswith(".parquet"):
        parquet_files = [out_path] if out_path.exists() else []
    else:
        parquet_files = list(out_path.glob("**/*.parquet"))
    total_parquet_bytes = sum(f.stat().st_size for f in parquet_files)

    if total_csv_bytes > 0:
        reduction_pct = (1.0 - (total_parquet_bytes / total_csv_bytes)) * 100.0
    else:
        reduction_pct = 0.0

    partitions = sorted(list({p.parent.name for p in parquet_files if "=" in p.parent.name}))
    meets_target = reduction_pct >= min_reduction_pct

    summary = {
        "rows_processed": total_rows,
        "input_files_count": len(input_files),
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
    logger.info("Linhas processadas:    %d", total_rows)
    logger.info("Tamanho CSV bruto:     %.2f KB", summary["csv_size_kb"])
    logger.info("Tamanho Parquet final: %.2f KB", summary["parquet_size_kb"])
    logger.info("Redução volumétrica:   %.2f%%", summary["reduction_pct"])
    if partitions:
        logger.info("Partições geradas:     %s", partitions)

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


def process_all_datasets(
    datasets_dir: Union[str, Path] = "datasets",
    output_base: Union[str, Path] = "data/processed",
) -> List[Dict[str, Any]]:
    """Converte sistematicamente todos os datasets de Câmara, Senado e TSE para Parquet."""
    ds_path = Path(datasets_dir)
    out_base = Path(output_base)
    summaries = []

    tasks = [
        # Câmara
        {
            "name": "Câmara - Deputados (Cadastro)",
            "input": ds_path / "camara/cadastro/deputados.csv",
            "output": out_base / "camara/deputados.parquet",
            "encoding": "utf8", "delimiter": ";", "partition_col": None,
        },
        {
            "name": "Câmara - CEAP (Cota Parlamentar)",
            "input": ds_path / "camara/ceap",
            "output": out_base / "camara/ceap",
            "encoding": "utf8", "delimiter": ";", "partition_col": "ano",
        },
        {
            "name": "Câmara - Proposições",
            "input": ds_path / "camara/proposicoes",
            "output": out_base / "camara/proposicoes",
            "encoding": "utf8", "delimiter": ";", "partition_col": "ano",
        },
        {
            "name": "Câmara - Proposições Autores",
            "input": ds_path / "camara/proposicoes_autores",
            "output": out_base / "camara/proposicoes_autores",
            "encoding": "utf8", "delimiter": ";", "partition_col": "ano",
        },

        # Senado
        {
            "name": "Senado - Senadores (Cadastro)",
            "input": ds_path / "senado/cadastro/senadores.csv",
            "output": out_base / "senado/senadores.parquet",
            "encoding": "utf8", "delimiter": ";", "partition_col": None,
        },
        {
            "name": "Senado - CEAPS (Cota Senadores)",
            "input": ds_path / "senado/ceaps",
            "output": out_base / "senado/ceaps",
            "encoding": "utf8", "delimiter": ";", "partition_col": "ano",
        },
        {
            "name": "Senado - Matérias",
            "input": ds_path / "senado/materias/materias.csv",
            "output": out_base / "senado/materias.parquet",
            "encoding": "utf8", "delimiter": ",", "partition_col": None,
        },

        # TSE - Candidatos & Complementar
        {
            "name": "TSE - Candidatos",
            "input": ds_path / "tse/candidatos",
            "output": out_base / "tse/candidatos",
            "encoding": "latin1", "delimiter": ";", "partition_col": "ano",
            "prefer_brasil": True,
            "filter_pattern": "consulta_cand_20",
        },
        {
            "name": "TSE - Candidatos Complementar",
            "input": ds_path / "tse/candidatos",
            "output": out_base / "tse/candidatos_complementar",
            "encoding": "latin1", "delimiter": ";", "partition_col": "ano",
            "prefer_brasil": True,
            "filter_pattern": "consulta_cand_complementar_20",
        },

        # TSE - Bens
        {
            "name": "TSE - Bens de Candidatos",
            "input": ds_path / "tse/bens",
            "output": out_base / "tse/bens",
            "encoding": "latin1", "delimiter": ";", "partition_col": "ano",
            "prefer_brasil": True,
        },

        # TSE - Coligações
        {
            "name": "TSE - Coligações e Federações",
            "input": ds_path / "tse/coligacoes",
            "output": out_base / "tse/coligacoes",
            "encoding": "latin1", "delimiter": ";", "partition_col": "ano",
            "prefer_brasil": True,
        },

        # TSE - Cassação
        {
            "name": "TSE - Motivo Cassação",
            "input": ds_path / "tse/cassacao",
            "output": out_base / "tse/cassacao",
            "encoding": "latin1", "delimiter": ";", "partition_col": "ano",
            "prefer_brasil": True,
        },

        # TSE - Prestação de Contas
        {
            "name": "TSE - Prestação de Contas (Despesas Pagas)",
            "input": ds_path / "tse/prestacao_contas",
            "output": out_base / "tse/prestacao_contas/despesas_pagas",
            "encoding": "latin1", "delimiter": ";", "partition_col": "ano",
            "filter_pattern": "despesas_pagas_candidatos",
            "prefer_brasil": True,
        },
        {
            "name": "TSE - Prestação de Contas (Despesas Contratadas)",
            "input": ds_path / "tse/prestacao_contas",
            "output": out_base / "tse/prestacao_contas/despesas_contratadas",
            "encoding": "latin1", "delimiter": ";", "partition_col": "ano",
            "filter_pattern": "despesas_contratadas_candidatos",
            "prefer_brasil": True,
        },
        {
            "name": "TSE - Prestação de Contas (Receitas)",
            "input": ds_path / "tse/prestacao_contas",
            "output": out_base / "tse/prestacao_contas/receitas",
            "encoding": "latin1", "delimiter": ";", "partition_col": "ano",
            "filter_pattern": "receitas_candidatos_20",
            "prefer_brasil": True,
        },

        # TSE - Redes Sociais
        {
            "name": "TSE - Redes Sociais",
            "input": ds_path / "tse/redes_sociais",
            "output": out_base / "tse/redes_sociais",
            "encoding": "latin1", "delimiter": ";", "partition_col": "ano",
        },

        # TSE - Votação Munzona
        {
            "name": "TSE - Votação Munzona (2022)",
            "input": ds_path / "tse/votacao/munzona/votacao_candidato_munzona_2022",
            "output": out_base / "tse/votacao_munzona",
            "encoding": "latin1", "delimiter": ";", "partition_col": "ano",
            "prefer_brasil": True,
        },

        # TSE - Totalização Presidente 2022
        {
            "name": "TSE - Totalização Presidencial 2022",
            "input": ds_path / "tse/votacao/totalizacao",
            "output": out_base / "tse/totalizacao_presidente_2022",
            "encoding": "latin1", "delimiter": ";", "partition_col": None,
        },

        # TSE - Detalhe Votação Seção 2022
        {
            "name": "TSE - Detalhe Votação Seção 2022",
            "input": ds_path / "tse/votacao/secao/detalhe_votacao_secao_2022",
            "output": out_base / "tse/detalhe_votacao_secao_2022",
            "encoding": "latin1", "delimiter": ";", "partition_col": "ano",
            "prefer_brasil": True,
        },
    ]

    logger.info(">>> Iniciando processamento em lote de %d conjuntos de dados <<<", len(tasks))

    for idx, task in enumerate(tasks, 1):
        task_input = Path(task["input"])
        if not task_input.exists():
            logger.warning("[%d/%d] Pulando '%s': caminho não encontrado (%s)", idx, len(tasks), task["name"], task_input)
            continue

        logger.info("\n------------------------------------------------------------")
        logger.info("[%d/%d] Processando: %s", idx, len(tasks), task["name"])
        logger.info("Origem:  %s", task["input"])
        logger.info("Destino: %s", task["output"])
        logger.info("------------------------------------------------------------")

        try:
            summary = process_csv_to_parquet(
                input_path=task["input"],
                output_dir=task["output"],
                encoding=task.get("encoding", "latin1"),
                delimiter=task.get("delimiter", ";"),
                partition_col=task.get("partition_col", "ano"),
                prefer_brasil=task.get("prefer_brasil", False),
                filter_pattern=task.get("filter_pattern"),
                min_reduction_pct=task.get("min_reduction_pct", 50.0),
            )
            summary["dataset_name"] = task["name"]
            summaries.append(summary)
        except Exception as e:
            logger.error("Erro ao processar '%s': %s", task["name"], e, exc_info=True)

    logger.info("\n============================================================")
    logger.info("        FINALIZADO PROCESSAMENTO DE TODOS OS DATASETS       ")
    logger.info("============================================================")
    logger.info("Total de conjuntos processados com sucesso: %d / %d", len(summaries), len(tasks))
    return summaries


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
        "--all",
        action="store_true",
        help="Processa todos os conjuntos de dados organizados em datasets/ gerando os Parquets correspondentes.",
    )
    parser.add_argument(
        "--datasets-dir",
        default="datasets",
        help="Diretório raiz dos datasets (padrão: datasets).",
    )
    return parser.parse_args(args)


def main() -> None:
    """Ponto de entrada CLI do pipeline de ETL."""
    args = parse_args()
    try:
        if args.all:
            summaries = process_all_datasets(
                datasets_dir=args.datasets_dir,
                output_base="data/processed",
            )
            if not summaries:
                sys.exit(1)
            sys.exit(0)

        summary = process_csv_to_parquet(
            input_path=args.input_path,
            output_dir=args.output_dir,
            encoding=args.encoding,
            delimiter=args.delimiter,
            compression=args.compression,
            compression_level=args.compression_level,
            partition_col=args.partition_col,
            min_reduction_pct=args.min_reduction,
        )
        if not summary["meets_target"]:
            logger.warning("Pipeline finalizou com redução abaixo da meta.")
        sys.exit(0)
    except Exception as e:
        logger.error("Erro na execução do pipeline ETL: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
