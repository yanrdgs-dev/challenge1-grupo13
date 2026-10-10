"""Pipeline ETL para materialização da tabela dimensional canônica dim_politicos.parquet.

Cruza dados da Câmara, Senado e TSE em estrita conformidade com:
- Princípio II da Constituição (matching determinístico por nome normalizado + UF/cargo, sem CPF);
- Princípio X da Constituição (stack 100% Python via Polars/DuckDB).
"""

import logging
import os
import re
from pathlib import Path
from typing import List, Optional

import duckdb
import polars as pl

from src.tools.normalizer import normalize_text, strip_accents

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ETL.BuildDimPoliticos")

EXPECTED_DIM_COLUMNS: List[str] = [
    "sq_candidato",
    "ideCadastro",
    "cod_senador",
    "nome_civil",
    "nome_urna",
    "nome_normalizado",
    "casa",
    "cargo",
    "uf",
    "partido",
    "mandato_anos",
]


def extract_id_from_uri(uri: Optional[str]) -> Optional[int]:
    """Extrai o id numérico a partir da URI oficial da Câmara dos Deputados."""
    if not uri:
        return None
    match = re.search(r"/(\d+)$", str(uri).strip())
    return int(match.group(1)) if match else None


def build_dim_politicos_df(
    deputados_df: pl.DataFrame,
    senadores_df: pl.DataFrame,
    tse_candidatos_df: Optional[pl.DataFrame] = None,
    ceap_meta_df: Optional[pl.DataFrame] = None,
) -> pl.DataFrame:
    """Consolida os registros de deputados e senadores em um DataFrame canônico unificado.

    Args:
        deputados_df: DataFrame bruto da Câmara (com uri, nome, nomeCivil).
        senadores_df: DataFrame bruto do Senado (com Nome Parlamentar, UF, Partido).
        tse_candidatos_df: DataFrame opcional do TSE (com SQ_CANDIDATO, NM_CANDIDATO, etc.).
        ceap_meta_df: DataFrame opcional da CEAP para enriquecimento de UF/partido.

    Returns:
        DataFrame dimensional unificado contendo estritamente as colunas de EXPECTED_DIM_COLUMNS.
    """
    records: List[dict] = []

    # 1. Mapeamento de Metadados CEAP (ideCadastro -> (sgUF, sgPartido))
    ceap_map = {}
    if ceap_meta_df is not None and not ceap_meta_df.is_empty():
        for row in ceap_meta_df.iter_rows(named=True):
            ide = row.get("ideCadastro")
            if ide:
                try:
                    ide_int = int(str(ide).strip())
                    ceap_map[ide_int] = {
                        "uf": str(row.get("sgUF") or "").strip().upper() or None,
                        "partido": str(row.get("sgPartido") or "").strip().upper() or None,
                    }
                except ValueError:
                    pass

    # 2. Mapeamento TSE (nome_norm + uf -> (SQ_CANDIDATO, NM_URNA, SG_PARTIDO))
    tse_map = {}
    if tse_candidatos_df is not None and not tse_candidatos_df.is_empty():
        for row in tse_candidatos_df.iter_rows(named=True):
            nm = row.get("NM_CANDIDATO") or ""
            uf = (row.get("SG_UF") or "").strip().upper()
            norm = normalize_text(nm)
            if norm and uf:
                key = (norm, uf)
                if key not in tse_map:
                    tse_map[key] = {
                        "sq_candidato": row.get("SQ_CANDIDATO"),
                        "nome_urna": row.get("NM_URNA_CANDIDATO"),
                        "partido": row.get("SG_PARTIDO"),
                    }

    # 3. Processa Deputados Federais
    if deputados_df is not None and not deputados_df.is_empty():
        for row in deputados_df.iter_rows(named=True):
            uri = row.get("uri")
            ide = extract_id_from_uri(uri)
            nome_civil = str(row.get("nomeCivil") or row.get("nome") or "").strip()
            nome_urna = str(row.get("nome") or "").strip()
            nome_norm = normalize_text(nome_civil)

            # Busca UF e Partido prioritariamente na CEAP, depois na própria linha
            meta = ceap_map.get(ide, {})
            uf = meta.get("uf") or str(row.get("ufNascimento") or row.get("siglaUf") or "").strip().upper() or None
            partido = meta.get("partido") or str(row.get("siglaPartido") or "").strip().upper() or None

            # Enriquece com TSE se houver correspondência por nome + UF
            sq_cand = None
            if uf and (nome_norm, uf) in tse_map:
                tse_info = tse_map[(nome_norm, uf)]
                sq_cand = tse_info.get("sq_candidato")
                if not partido:
                    partido = tse_info.get("partido")

            records.append({
                "sq_candidato": int(sq_cand) if sq_cand is not None else None,
                "ideCadastro": int(ide) if ide is not None else None,
                "cod_senador": None,
                "nome_civil": nome_civil.upper(),
                "nome_urna": nome_urna,
                "nome_normalizado": nome_norm,
                "casa": "Câmara dos Deputados",
                "cargo": "Deputado Federal",
                "uf": uf,
                "partido": partido,
                "mandato_anos": "2023-2027",
            })

    # 4. Processa Senadores
    if senadores_df is not None and not senadores_df.is_empty():
        for row in senadores_df.iter_rows(named=True):
            nome_parlamentar = str(row.get("Nome Parlamentar") or "").strip()
            uf = str(row.get("UF") or "").strip().upper() or None
            partido = str(row.get("Partido") or "").strip().upper() or None
            mandato = str(row.get("Mandato") or "").strip() or "2019-2027"
            nome_norm = normalize_text(nome_parlamentar)

            # Busca TSE para obter SQ_CANDIDATO
            sq_cand = None
            if uf and (nome_norm, uf) in tse_map:
                sq_cand = tse_map[(nome_norm, uf)].get("sq_candidato")

            # código oficial do Senado: é a chave que a tool de gastos do Senado (COD_SENADOR) usa
            cod_raw = str(row.get("Codigo Parlamentar") or "").strip()
            cod_senador = int(cod_raw) if cod_raw.isdigit() else None

            records.append({
                "sq_candidato": int(sq_cand) if sq_cand is not None else None,
                "ideCadastro": None,
                "cod_senador": cod_senador,
                "nome_civil": nome_parlamentar.upper(),
                "nome_urna": nome_parlamentar,
                "nome_normalizado": nome_norm,
                "casa": "Senado Federal",
                "cargo": "Senador",
                "uf": uf,
                "partido": partido,
                "mandato_anos": mandato,
            })

    # Cria DataFrame e aplica casts explícitos
    schema = {
        "sq_candidato": pl.Int64,
        "ideCadastro": pl.Int64,
        "cod_senador": pl.Int64,
        "nome_civil": pl.Utf8,
        "nome_urna": pl.Utf8,
        "nome_normalizado": pl.Utf8,
        "casa": pl.Utf8,
        "cargo": pl.Utf8,
        "uf": pl.Utf8,
        "partido": pl.Utf8,
        "mandato_anos": pl.Utf8,
    }

    if not records:
        return pl.DataFrame([], schema=schema)

    df_out = pl.DataFrame(records, schema=schema)

    # Elimina qualquer eventual coluna sensível (Garantia Constitucional - Princípio II)
    cols_to_drop = [c for c in df_out.columns if "cpf" in c.lower()]
    if cols_to_drop:
        df_out = df_out.drop(cols_to_drop)

    return df_out.select(EXPECTED_DIM_COLUMNS)


def build_and_save_dim_politicos(
    output_path: str = "data/processed/dim_politicos.parquet",
    camara_deputados_path: str = "data/processed/camara/deputados.parquet",
    senado_senadores_path: str = "data/processed/senado/senadores.parquet",
    camara_ceap_pattern: str = "data/processed/camara/ceap/**/*.parquet",
    tse_candidatos_pattern: str = "data/processed/tse/candidatos/**/*.parquet",
) -> Path:
    """Executa a materialização de dim_politicos.parquet a partir dos arquivos processados."""
    logger.info("Iniciando construção de dim_politicos.parquet...")

    con = duckdb.connect()

    # 1. Carrega Deputados
    logger.info("Carregando deputados de %s...", camara_deputados_path)
    dep_df = pl.from_arrow(con.query(f"SELECT * FROM '{camara_deputados_path}'").arrow())

    # 2. Carrega Senadores
    logger.info("Carregando senadores de %s...", senado_senadores_path)
    sen_df = pl.from_arrow(con.query(f"SELECT * FROM '{senado_senadores_path}'").arrow())

    # 3. Metadados CEAP (ideCadastro, sgUF, sgPartido)
    logger.info("Extraindo metadados da CEAP...")
    ceap_meta_df = pl.from_arrow(
        con.query(f"""
            SELECT DISTINCT
                ideCadastro,
                sgUF,
                sgPartido
            FROM '{camara_ceap_pattern}'
            WHERE ideCadastro IS NOT NULL
        """).arrow()
    )

    # 4. Candidatos TSE
    logger.info("Extraindo candidatos federais do TSE...")
    tse_df = pl.from_arrow(
        con.query(f"""
            SELECT
                SQ_CANDIDATO,
                NM_CANDIDATO,
                NM_URNA_CANDIDATO,
                SG_UF,
                SG_PARTIDO,
                DS_CARGO
            FROM '{tse_candidatos_pattern}'
            WHERE DS_CARGO IN ('DEPUTADO FEDERAL', 'SENADOR')
        """).arrow()
    )

    con.close()

    # Constrói DataFrame canônico
    dim_df = build_dim_politicos_df(
        deputados_df=dep_df,
        senadores_df=sen_df,
        tse_candidatos_df=tse_df,
        ceap_meta_df=ceap_meta_df,
    )

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    dim_df.write_parquet(out_file)
    logger.info("dim_politicos.parquet salvo com sucesso em %s (%d registros).", out_file, len(dim_df))
    return out_file


if __name__ == "__main__":
    build_and_save_dim_politicos()
