"""
Script de Análise Exploratória de Dados (EDA) - Eixo 3: Atividade Legislativa e Autoria.
Abrange:
- Câmara dos Deputados: Proposições (140.507) e Autores (456.351)
- Senado Federal: Matérias Legislativas (9.922)
"""

import sys
import re
from pathlib import Path
import polars as pl

def fix_mojibake(text: str) -> str:
    """Corrige texto duplamente codificado em UTF-8 através de CP1252."""
    if not text:
        return ""
    try:
        # Tenta reverter a codificação CP1252 -> UTF-8
        t1 = text.encode("cp1252", errors="ignore").decode("utf-8", errors="ignore")
        try:
            return t1.encode("cp1252", errors="ignore").decode("utf-8", errors="ignore")
        except Exception:
            return t1
    except Exception:
        return text

def main():
    print("=" * 70)
    print("INICIANDO EDA - EIXO 3: ATIVIDADE LEGISLATIVA, AUTORIA E TRAMITAÇÃO")
    print("=" * 70)

    # 1. Carregamento dos dados
    prop_path = "data/processed/camara/proposicoes/**/*.parquet"
    aut_path = "data/processed/camara/proposicoes_autores/**/*.parquet"
    mat_path = "data/processed/senado/materias.parquet"

    print("\n>>> 1. VOLUME E VISÃO GERAL")
    df_prop = pl.read_parquet(prop_path)
    df_aut = pl.read_parquet(aut_path)
    df_mat = pl.read_parquet(mat_path)

    print(f"Câmara - Proposições: {len(df_prop):,} registros, {len(df_prop.columns)} colunas")
    print(f"Câmara - Autores: {len(df_aut):,} registros, {len(df_aut.columns)} colunas")
    print(f"Senado - Matérias: {len(df_mat):,} registros, {len(df_mat.columns)} colunas")

    # 2. Taxonomia e Classificação das Proposições da Câmara
    print("\n>>> 2. TAXONOMIA DAS PROPOSIÇÕES (CÂMARA)")
    
    # Classificar tipos em Substantivos (com força de lei) vs Regimentais / Acessórios
    tipos_substantivos = {"PL", "PLP", "PEC", "MPV", "PDL"}
    tipos_instrumentais = {"RPD", "PRL", "REQ", "RIC", "EMC", "PAR", "INC", "DOC", "SBT"}

    df_prop_class = df_prop.with_columns(
        pl.when(pl.col("siglaTipo").is_in(list(tipos_substantivos)))
        .then(pl.lit("Substantivo (Força de Lei)"))
        .when(pl.col("siglaTipo").is_in(list(tipos_instrumentais)))
        .then(pl.lit("Regimental / Instrumental"))
        .otherwise(pl.lit("Outros Atos"))
        .alias("categoria_ato")
    )

    resumo_cat = df_prop_class.group_by("categoria_ato").agg(
        pl.len().alias("quantidade")
    ).with_columns(
        (pl.col("quantidade") / len(df_prop) * 100).round(2).alias("percentual")
    ).sort("quantidade", descending=True)
    print(resumo_cat)

    print("\nTop 10 Siglas de Tipos de Proposição:")
    top_tipos = (
        df_prop.group_by(["siglaTipo", "descricaoTipo"])
        .agg(pl.len().alias("quantidade"))
        .with_columns(
            (pl.col("quantidade") / len(df_prop) * 100).round(2).alias("percentual")
        )
        .sort("quantidade", descending=True)
        .head(10)
    )
    print(top_tipos)

    # 3. Funil de Tramitação e Desfecho na Câmara
    print("\n>>> 3. FUNIL DE TRAMITAÇÃO E STATUS (CÂMARA)")
    situacoes = (
        df_prop.with_columns(
            pl.when(pl.col("ultimoStatus_descricaoSituacao").is_null() | (pl.col("ultimoStatus_descricaoSituacao") == ""))
            .then(pl.lit("Em Tramitação Inicial / Sem Despacho Conclusivo"))
            .otherwise(pl.col("ultimoStatus_descricaoSituacao"))
            .alias("situacao_limpa")
        )
        .group_by("situacao_limpa")
        .agg(pl.len().alias("quantidade"))
        .with_columns(
            (pl.col("quantidade") / len(df_prop) * 100).round(2).alias("percentual")
        )
        .sort("quantidade", descending=True)
    )
    print(situacoes.head(8))

    # Verificar proposições que viraram norma jurídica na Câmara
    virou_norma = df_prop.filter(
        pl.col("urnFinal").is_not_null() & (pl.col("urnFinal") != "")
    ).height
    print(f"\nProposições da Câmara com Norma Jurídica Final Gerada (urnFinal preenchida): {virou_norma:,} ({virou_norma/len(df_prop)*100:.2f}%)")

    # 4. Autoria, Coautoria e Subscrição (Câmara)
    print("\n>>> 4. ANÁLISE DE AUTORIA E COAUTORIA (CÂMARA)")
    print(f"Total de relações autor-proposição: {len(df_aut):,}")
    
    # Distribuição por tipo de autor
    print("\nDistribuição por Tipo de Autor:")
    print(df_aut.group_by("tipoAutor").agg(pl.len().alias("qtd")).sort("qtd", descending=True).head(6))

    # Filtrar apenas deputados
    aut_dep = df_aut.filter(pl.col("tipoAutor") == "Deputado(a)")
    print(f"\nAssinaturas atribuídas a Deputados: {len(aut_dep):,}")

    # Separar autor principal (proponente == 1 e ordemAssinatura == 1) de cosignatários
    aut_dep_status = aut_dep.with_columns(
        pl.when((pl.col("proponente") == 1) | (pl.col("ordemAssinatura") == 1))
        .then(pl.lit("Autor Principal"))
        .otherwise(pl.lit("Cosignatário / Apoiador"))
        .alias("papel_autoria")
    )
    print("\nPapel da Assinatura dos Deputados:")
    print(aut_dep_status.group_by("papel_autoria").agg(pl.len().alias("qtd")).with_columns(
        (pl.col("qtd") / len(aut_dep) * 100).round(2).alias("pct")
    ))

    # Join com proposições para avaliar autores de Projetos de Lei (PL, PEC, PLP)
    df_aut_prop = aut_dep_status.join(
        df_prop.select(["id", "siglaTipo", "numero", "ano", "ementa"]),
        left_on="idProposicao",
        right_on="id",
        how="inner"
    )

    print("\nTop 10 Deputados com MAIOR número de PROJETOS DE LEI (PL/PEC/PLP) como AUTOR PRINCIPAL:")
    top_pls_principais = (
        df_aut_prop.filter(
            pl.col("siglaTipo").is_in(["PL", "PEC", "PLP"]) & 
            (pl.col("papel_autoria") == "Autor Principal")
        )
        .group_by(["nomeAutor", "siglaPartidoAutor", "siglaUFAutor"])
        .agg(pl.len().alias("total_projetos_principais"))
        .sort("total_projetos_principais", descending=True)
        .head(10)
    )
    print(top_pls_principais)

    print("\nTop 10 Deputados com MAIOR número de ASSINATURAS EM MASSA (Cosignatários/Requerimentos):")
    top_cosignatarios = (
        df_aut_prop.filter(pl.col("papel_autoria") == "Cosignatário / Apoiador")
        .group_by(["nomeAutor", "siglaPartidoAutor", "siglaUFAutor"])
        .agg(pl.len().alias("total_coautorias"))
        .sort("total_coautorias", descending=True)
        .head(10)
    )
    print(top_cosignatarios)

    # 5. Mineração Textual de Ementas por Temas Sensíveis de Fact-Checking
    print("\n>>> 5. MINERAÇÃO TEMÁTICA DE EMENTAS (FACT-CHECKING)")
    
    # Dicionário de temas com regex correspondentes
    temas = {
        "Armas / CACs / Tiro Esportivo": r"(?i)\b(arma|armas|porte de arma|posse de arma|cac|cacs|tiro esportivo|desarmamento)\b",
        "Tributos / Impostos / PIX": r"(?i)\b(imposto|tribut|tributaria|cpmf|pix|irpf|isencao fiscal|taxa|taxacao)\b",
        "Saúde / Vacinas / Aborto": r"(?i)\b(vacina|vacinacao|aborto|covid|anvisa|saude publica|medicamento)\b",
        "Segurança / Crime / Maioridade": r"(?i)\b(penal|crime|criminoso|homicidio|faccao|maioridade penal|preso|cadeia)\b",
        "Tecnologia / Internet / Redes / IA": r"(?i)\b(internet|redes sociais|inteligencia artificial|fake news|plataforma digital|desinformacao)\b",
        "Drogas / Maconha": r"(?i)\b(droga|drogas|maconha|cannabis|entorpecente)\b",
        "Meio Ambiente / Indígenas / Marco Temporal": r"(?i)\b(indigena|marco temporal|desmatamento|queimada|ambiental|ibama)\b"
    }

    print("\nVolume de Projetos de Lei (PL, PEC, PLP, MPV) por Tema de Alto Impacto:")
    pls_df = df_prop.filter(pl.col("siglaTipo").is_in(["PL", "PEC", "PLP", "MPV"]))
    
    temas_stats = []
    for nome_tema, rgx in temas.items():
        matched = pls_df.filter(pl.col("ementa").str.contains(rgx))
        temas_stats.append({
            "tema": nome_tema,
            "qtd_projetos": len(matched),
            "pct_dos_pls": round(len(matched) / len(pls_df) * 100, 2)
        })
    df_temas = pl.DataFrame(temas_stats).sort("qtd_projetos", descending=True)
    print(df_temas)

    # 6. Senado Federal: Matérias, Relatorias e Conversão em Lei
    print("\n>>> 6. SENADO FEDERAL: MATÉRIAS E STATUS DE CONVERSÃO")
    # Tratar texto do senado
    df_mat_clean = df_mat.with_columns(
        pl.col("identificacao").map_elements(fix_mojibake, return_dtype=pl.String).alias("identificacao_limpa"),
        pl.col("ementa").map_elements(fix_mojibake, return_dtype=pl.String).alias("ementa_limpa"),
        pl.col("autoria").map_elements(fix_mojibake, return_dtype=pl.String).alias("autoria_limpa"),
        pl.col("situacaoAtual").map_elements(fix_mojibake, return_dtype=pl.String).alias("situacao_limpa")
    )

    print(f"Total de Matérias do Senado: {len(df_mat_clean):,}")
    print("\nStatus de Tramitação no Senado:")
    print(df_mat_clean.group_by("tramitando").agg(pl.len().alias("qtd")))

    print("\nTop 5 Situações no Senado:")
    print(df_mat_clean.group_by("situacao_limpa").agg(pl.len().alias("qtd")).sort("qtd", descending=True).head(5))

    # Conversão em norma no Senado
    com_norma = df_mat_clean.filter(pl.col("normaGerada").is_not_null() & (pl.col("normaGerada") != "")).height
    print(f"\nMatérias com Norma Gerada no Senado: {com_norma:,} de {len(df_mat_clean):,} ({com_norma/len(df_mat_clean)*100:.2f}%)")

    # 7. Rastreabilidade Documental (Links para Íntegra em PDF)
    print("\n>>> 7. RASTREABILIDADE DE TEXTOS INTEGRAIS (PDF)")
    link_camara = df_prop.filter(pl.col("urlInteiroTeor").is_not_null() & (pl.col("urlInteiroTeor") != "")).height
    print(f"Proposições da Câmara com link para Íntegra em PDF: {link_camara:,} de {len(df_prop):,} ({link_camara/len(df_prop)*100:.1f}%)")
    
    link_senado = df_mat_clean.filter(pl.col("urlDocumento").is_not_null() & (pl.col("urlDocumento") != "")).height
    print(f"Matérias do Senado com link para Íntegra em PDF: {link_senado:,} de {len(df_mat_clean):,} ({link_senado/len(df_mat_clean)*100:.1f}%)")

    print("\n" + "=" * 70)
    print("EDA DO EIXO 3 EXECUTADA COM SUCESSO!")
    print("=" * 70)

if __name__ == "__main__":
    main()
