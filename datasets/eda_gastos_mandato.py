"""
Script de Análise Exploratória de Dados (EDA) - Eixo 2: Gastos do Mandato e Cota Parlamentar.
Abrange:
- Câmara dos Deputados: CEAP (2022-2026)
- Senado Federal: CEAPS (2022-2026)
- TSE: Prestação de Contas (Despesas Contratadas e Pagas) para cruzamento de fornecedores
"""

import sys
import json
import re
from pathlib import Path
import polars as pl

def clean_cnpj(col_expr: pl.Expr) -> pl.Expr:
    """Remove caracteres especiais e preenche com zeros à esquerda se for CNPJ (14 dígitos)."""
    digits_only = col_expr.cast(pl.String).str.replace_all(r"[^\d]", "")
    # Se tiver entre 12 e 14 dígitos, padroniza com 14 zeros à esquerda
    return (
        pl.when(digits_only.str.len_chars() >= 11)
        .then(digits_only.str.zfill(14))
        .otherwise(None)
    )

def main():
    print("=" * 70)
    print("INICIANDO EDA - EIXO 2: GASTOS DO MANDATO E COTA PARLAMENTAR")
    print("=" * 70)

    # 1. Carregamento e Visão Geral
    ceap_path = "data/processed/camara/ceap/**/*.parquet"
    ceaps_path = "data/processed/senado/ceaps/**/*.parquet"
    tse_contratadas_path = "data/processed/tse/prestacao_contas/despesas_contratadas/**/*.parquet"

    print("\n>>> 1. VOLUME E RESUMO GERAL DAS BASES")
    df_ceap = pl.read_parquet(ceap_path)
    print(f"Câmara CEAP: {len(df_ceap):,} linhas, {len(df_ceap.columns)} colunas")
    
    df_ceaps = pl.read_parquet(ceaps_path)
    print(f"Senado CEAPS: {len(df_ceaps):,} linhas, {len(df_ceaps.columns)} colunas")

    # Totais financeiros
    total_camara = df_ceap["vlrLiquido"].sum()
    total_senado = df_ceaps["VALOR_REEMBOLSADO"].sum()
    print(f"Total reembolsado Câmara (2022-2026): R$ {total_camara:,.2f}")
    print(f"Total reembolsado Senado (2022-2026): R$ {total_senado:,.2f}")
    print(f"Total consolidado Congresso: R$ {total_camara + total_senado:,.2f}")

    # Totais por ano
    print("\nGastos por Ano - Câmara:")
    print(df_ceap.group_by("ano").agg(
        pl.len().alias("qtd_notas"),
        pl.col("vlrLiquido").sum().alias("total_reembolsado"),
        pl.col("txNomeParlamentar").n_unique().alias("deputados_ativos")
    ).sort("ano"))

    print("\nGastos por Ano - Senado:")
    print(df_ceaps.group_by("ano").agg(
        pl.len().alias("qtd_notas"),
        pl.col("VALOR_REEMBOLSADO").sum().alias("total_reembolsado"),
        pl.col("NOME_SENADOR").n_unique().alias("senadores_ativos")
    ).sort("ano"))

    # 2. Sazonalidade Temporal Mensal (2022 a 2026)
    print("\n>>> 2. SAZONALIDADE MENSAL (CÂMARA)")
    sazonalidade_camara = (
        df_ceap.filter(pl.col("numAno").is_between(2022, 2025))
        .group_by(["numAno", "numMes"])
        .agg(pl.col("vlrLiquido").sum().alias("total_mes"))
        .sort(["numAno", "numMes"])
    )
    print("Primeiros e últimos meses analisados:")
    print(sazonalidade_camara.head(5))
    print(sazonalidade_camara.tail(5))

    # 3. Categorias de Despesas (Pareto)
    print("\n>>> 3. TOP CATEGORIAS DE DESPESAS")
    print("\nCâmara dos Deputados (Top 8):")
    cat_camara = (
        df_ceap.group_by("txtDescricao")
        .agg(
            pl.len().alias("qtd_notas"),
            pl.col("vlrLiquido").sum().alias("total_gasto")
        )
        .with_columns(
            (pl.col("total_gasto") / total_camara * 100).round(2).alias("pct_total")
        )
        .sort("total_gasto", descending=True)
    )
    print(cat_camara.head(8))

    print("\nSenado Federal (Top 8):")
    cat_senado = (
        df_ceaps.group_by("TIPO_DESPESA")
        .agg(
            pl.len().alias("qtd_notas"),
            pl.col("VALOR_REEMBOLSADO").sum().alias("total_gasto")
        )
        .with_columns(
            (pl.col("total_gasto") / total_senado * 100).round(2).alias("pct_total")
        )
        .sort("total_gasto", descending=True)
    )
    print(cat_senado.head(8))

    # 4. Distribuição por Parlamentar (Gasto Médio Anual e Percentis)
    print("\n>>> 4. DISTRIBUIÇÃO DE GASTOS POR PARLAMENTAR")
    # Focar nos anos fechados (2023, 2024) para comparar deputados de mandato pleno
    gastos_dep_2023 = (
        df_ceap.filter(pl.col("numAno") == 2023)
        .group_by(["txNomeParlamentar", "sgUF", "sgPartido"])
        .agg(
            pl.col("vlrLiquido").sum().alias("total_ano"),
            pl.len().alias("qtd_notas")
        )
        .sort("total_ano", descending=True)
    )
    print(f"Total de deputados que usaram cota em 2023: {len(gastos_dep_2023)}")
    percentis = [0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
    quantis = {f"P{int(p*100)}": gastos_dep_2023["total_ano"].quantile(p) for p in percentis}
    print(f"Mediana (P50) gasto deputado 2023: R$ {quantis['P50']:,.2f}")
    print(f"P25: R$ {quantis['P25']:,.2f} | P75: R$ {quantis['P75']:,.2f}")
    print(f"P90: R$ {quantis['P90']:,.2f} | P99: R$ {quantis['P99']:,.2f}")
    print(f"Média: R$ {gastos_dep_2023['total_ano'].mean():,.2f}")
    print(f"Máximo em 2023: R$ {gastos_dep_2023['total_ano'].max():,.2f} ({gastos_dep_2023['txNomeParlamentar'][0]} - {gastos_dep_2023['sgUF'][0]})")
    print(f"Mínimo em 2023: R$ {gastos_dep_2023['total_ano'].min():,.2f}")

    print("\nTop 5 Maiores Gastadores Câmara 2023:")
    print(gastos_dep_2023.head(5))

    print("\nTop 5 Menores Gastadores Câmara 2023 (que usaram):")
    print(gastos_dep_2023.tail(5))

    # 5. Análise de Fornecedores e Cruzamento de Redes (CEAP/CEAPS ↔ TSE)
    print("\n>>> 5. FORNECEDORES E CRUZAMENTO DETERMINÍSTICO COM TSE")
    # Fornecedores da Câmara
    # Fornecedores da Câmara agrupados estritamente por CNPJ limpo
    forn_camara = (
        df_ceap.with_columns(clean_cnpj(pl.col("txtCNPJCPF")).alias("cnpj_limpo"))
        .filter(pl.col("cnpj_limpo").is_not_null() & (pl.col("cnpj_limpo") != "00000000000001"))
        .group_by("cnpj_limpo")
        .agg(
            pl.col("txtFornecedor").first().alias("txtFornecedor"),
            pl.col("vlrLiquido").sum().alias("total_recebido_camara"),
            pl.len().alias("qtd_notas_camara"),
            pl.col("txNomeParlamentar").n_unique().alias("qtd_deputados_clientes")
        )
        .sort("total_recebido_camara", descending=True)
    )
    print(f"Fornecedores únicos com CNPJ válido na Câmara: {len(forn_camara):,}")
    print("\nTop 5 Fornecedores Câmara (Geral):")
    print(forn_camara.head(5))

    # Carregar TSE Despesas Contratadas com CNPJ limpo
    print("\nEscaneando fornecedores de campanha do TSE...")
    df_tse_forn = (
        pl.scan_parquet(tse_contratadas_path)
        .filter(pl.col("NR_CPF_CNPJ_FORNECEDOR").is_not_null())
        .with_columns(
            pl.col("NR_CPF_CNPJ_FORNECEDOR").cast(pl.String).str.zfill(14).alias("cnpj_limpo")
        )
        .filter(pl.col("cnpj_limpo") != "00000000000001")
        .group_by("cnpj_limpo")
        .agg(
            pl.col("NM_FORNECEDOR").first().alias("nm_fornecedor_tse"),
            pl.col("DS_CNAE_FORNECEDOR").first().alias("cnae_tse"),
            pl.col("VR_DESPESA_CONTRATADA").sum().alias("total_recebido_tse"),
            pl.len().alias("qtd_contratos_tse"),
            pl.col("NM_CANDIDATO").n_unique().alias("qtd_candidatos_clientes")
        )
        .collect()
    )
    print(f"Fornecedores únicos com CNPJ no TSE: {len(df_tse_forn):,}")

    # Cruzamento / Join
    overlap_fornecedores = forn_camara.join(df_tse_forn, on="cnpj_limpo", how="inner")
    print(f"\nFornecedores da Câmara que TAMBÉM prestaram serviços em campanhas no TSE: {len(overlap_fornecedores):,}")
    print(f"Taxa de sobreposição: {len(overlap_fornecedores) / len(forn_camara) * 100:.2f}% dos fornecedores da Câmara")

    # Ordenar por total combinado
    overlap_fornecedores = overlap_fornecedores.with_columns(
        (pl.col("total_recebido_camara") + pl.col("total_recebido_tse")).alias("total_combinado")
    ).sort("total_recebido_camara", descending=True)

    print("\nTop 10 Fornecedores Híbridos (Mandato Câmara + Campanha Eleitoral TSE):")
    for r in overlap_fornecedores.head(10).iter_rows(named=True):
        print(f"- CNPJ: {r['cnpj_limpo']} | {r['txtFornecedor'][:35]:35} | Câmara: R$ {r['total_recebido_camara']:>12,.2f} | TSE: R$ {r['total_recebido_tse']:>14,.2f} | Atividade: {str(r['cnae_tse'])[:30]}")

    # 6. Rastreabilidade Documental e Passagens Aéreas
    print("\n>>> 6. RASTREABILIDADE DOCUMENTAL, PASSAGENS E GLOSAS")
    # Documentos com link
    com_link = df_ceap.filter(pl.col("urlDocumento").is_not_null() & (pl.col("urlDocumento") != "")).height
    pct_link = (com_link / len(df_ceap)) * 100
    print(f"Despesas da Câmara com link direto para a NF-e/Recibo: {com_link:,} de {len(df_ceap):,} ({pct_link:.1f}%)")

    # Passagens aéreas
    df_passagens = df_ceap.filter(pl.col("txtDescricao").str.to_uppercase().str.contains("PASSAGEM"))
    print(f"\nTotal de registros de passagens aéreas na Câmara: {len(df_passagens):,}")
    pass_validos = df_passagens.filter(pl.col("txtPassageiro").is_not_null() & (pl.col("txtPassageiro") != ""))
    trech_validos = df_passagens.filter(pl.col("txtTrecho").is_not_null() & (pl.col("txtTrecho") != ""))
    print(f"Passageiros distintos registrados: {pass_validos['txtPassageiro'].n_unique():,}")
    print(f"Trechos distintos registrados: {trech_validos['txtTrecho'].n_unique():,}")
    
    # Top 5 Trechos mais voados
    top_trechos = (
        df_passagens.filter(pl.col("txtTrecho").is_not_null() & (pl.col("txtTrecho") != ""))
        .group_by("txtTrecho")
        .agg(pl.len().alias("voos"), pl.col("vlrLiquido").sum().alias("total_passagens"))
        .sort("voos", descending=True)
    )
    print("\nTop 5 Trechos Aéreos mais voados:")
    print(top_trechos.head(5))

    # Glosas (reembolsos negados ou reduzidos)
    df_glosas = df_ceap.filter(pl.col("vlrGlosa") > 0)
    print(f"\nDespesas com Glosa (valores rejeitados pela Câmara): {len(df_glosas):,} registros")
    print(f"Total glosado (economizado pelo erário): R$ {df_glosas['vlrGlosa'].sum():,.2f}")
    print(f"Maior glosa única: R$ {df_glosas['vlrGlosa'].max():,.2f}")

    print("\n" + "=" * 70)
    print("EDA DO EIXO 2 EXECUTADA COM SUCESSO!")
    print("=" * 70)

if __name__ == "__main__":
    main()
