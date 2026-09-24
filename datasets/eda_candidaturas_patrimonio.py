"""Script analítico de EDA profunda sobre Candidaturas, Informações Complementares e Bens do TSE."""

import polars as pl
import unicodedata
import json

def strip_accents(s: str) -> str:
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").upper().strip()

print("1. CARREGANDO DADOS...")
cand = pl.scan_parquet("data/processed/tse/candidatos").collect()
comp = pl.scan_parquet("data/processed/tse/candidatos_complementar").collect()
bens = pl.scan_parquet("data/processed/tse/bens").collect()
cass = pl.scan_parquet("data/processed/tse/cassacao").collect()
dep = pl.scan_parquet("data/processed/camara/deputados.parquet").collect()

print("\n--- 2. ANÁLISE DE CANDIDATURAS ---")
print("Total Candidaturas:", cand.shape[0])
print("Por ano:")
print(cand["ano"].value_counts())

print("\nPor Cargo (2022 - Eleições Gerais):")
print(cand.filter(pl.col("ano") == 2022)["DS_CARGO"].value_counts().head(10))

print("\nSituação da Candidatura (Geral):")
print(cand["DS_SITUACAO_CANDIDATURA"].value_counts().head(10))

print("\nResultado das Eleições 2022 (DS_SIT_TOT_TURNO):")
print(cand.filter(pl.col("ano") == 2022)["DS_SIT_TOT_TURNO"].value_counts())

print("\nPerfil Sociodemográfico 2022:")
print("Gênero:", cand.filter(pl.col("ano") == 2022)["DS_GENERO"].value_counts())
print("Cor/Raça:", cand.filter(pl.col("ano") == 2022)["DS_COR_RACA"].value_counts())
print("Escolaridade:", cand.filter(pl.col("ano") == 2022)["DS_GRAU_INSTRUCAO"].value_counts().head(5))

print("\n--- 3. ANÁLISE DE INFORMAÇÕES COMPLEMENTARES ---")
if "ST_REELEICAO" in comp.columns:
    print("Reeleição:", comp["ST_REELEICAO"].value_counts())
if "ST_QUILOMBOLA" in comp.columns:
    print("Quilombola:", comp["ST_QUILOMBOLA"].value_counts())
if "DS_ETNIA_INDIGENA" in comp.columns:
    print("Etnia Indígena:", comp.filter(pl.col("DS_ETNIA_INDIGENA") != "#NULO#")["DS_ETNIA_INDIGENA"].value_counts().head(5))

print("\n--- 4. ANÁLISE DE BENS E PATRIMÔNIO ---")
print("Total itens declarados:", bens.shape[0])
print("Soma total declarada (R$):", bens["VR_BEM_CANDIDATO"].sum())

# Agregação por candidato
bens_cand = bens.group_by(["ano", "SQ_CANDIDATO"]).agg([
    pl.sum("VR_BEM_CANDIDATO").alias("patrimonio_total"),
    pl.count("VR_BEM_CANDIDATO").alias("qtd_itens")
])

print("\nEstatísticas de Patrimônio Total por Candidato (Geral):")
q = [0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
for p in q:
    val = bens_cand["patrimonio_total"].quantile(p)
    print(f"Percentil {int(p*100)}%: R$ {val:,.2f}")

print("Média: R$", f"{bens_cand['patrimonio_total'].mean():,.2f}")
print("Mediana: R$", f"{bens_cand['patrimonio_total'].median():,.2f}")
print("Máximo: R$", f"{bens_cand['patrimonio_total'].max():,.2f}")

# Top 5 Maiores Patrimônios em 2022
top_2022 = (
    bens_cand.filter(pl.col("ano") == 2022)
    .join(cand.filter(pl.col("ano") == 2022), on="SQ_CANDIDATO")
    .sort("patrimonio_total", descending=True)
    .select(["NM_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "SG_UF", "DS_CARGO", "patrimonio_total", "DS_SIT_TOT_TURNO"])
    .head(5)
)
print("\nTop 5 Maiores Patrimônios Declarados (2022):")
print(top_2022)

# Cruzamento Patrimônio x Sucesso Eleitoral (Deputado Federal 2022)
df_dep_fed = (
    cand.filter((pl.col("ano") == 2022) & (pl.col("DS_CARGO") == "DEPUTADO FEDERAL"))
    .join(bens_cand.filter(pl.col("ano") == 2022), on="SQ_CANDIDATO", how="left")
    .with_columns(
        pl.col("patrimonio_total").fill_null(0.0),
        pl.when(pl.col("DS_SIT_TOT_TURNO").str.contains("ELEITO")).then(1).otherwise(0).alias("is_eleito")
    )
)

print("\nDeputados Federais 2022 - Eleitos vs Não Eleitos:")
print("Patrimônio Médio Eleitos: R$", f"{df_dep_fed.filter(pl.col('is_eleito') == 1)['patrimonio_total'].mean():,.2f}")
print("Patrimônio Mediano Eleitos: R$", f"{df_dep_fed.filter(pl.col('is_eleito') == 1)['patrimonio_total'].median():,.2f}")
print("Patrimônio Médio Não Eleitos: R$", f"{df_dep_fed.filter(pl.col('is_eleito') == 0)['patrimonio_total'].mean():,.2f}")
print("Patrimônio Mediano Não Eleitos: R$", f"{df_dep_fed.filter(pl.col('is_eleito') == 0)['patrimonio_total'].median():,.2f}")

print("\n--- 5. TESTE DE RESOLUÇÃO DE ENTIDADES (CÂMARA 57ª LEGISLATURA <-> TSE 2022) ---")
# Normalização
cand_2022_eleitos = cand.filter(
    (pl.col("ano") == 2022) & 
    (pl.col("DS_CARGO") == "DEPUTADO FEDERAL") & 
    (pl.col("DS_SIT_TOT_TURNO").str.contains("ELEITO|SUPLENTE"))
).with_columns([
    pl.col("NM_CANDIDATO").map_elements(strip_accents, return_dtype=pl.Utf8).alias("nome_norm"),
    pl.col("SG_UF").alias("uf_cand"),
    pl.col("SG_PARTIDO").alias("partido_cand"),
])

dep_norm = dep.with_columns([
    pl.col("nomeCivil").map_elements(strip_accents, return_dtype=pl.Utf8).alias("nome_norm"),
    pl.col("siglaUf").alias("uf_dep"),
    pl.col("siglaPartido").alias("partido_dep"),
])

# Match 1: Nome Civil Normalizado + UF
match_exato = dep_norm.join(cand_2022_eleitos, on=["nome_norm", "uf_cand"], how="inner")
print(f"Total de Deputados na Câmara: {dep.shape[0]}")
print(f"Matches exatos por (Nome Civil Normalizado + UF): {match_exato.shape[0]} / {dep.shape[0]} ({match_exato.shape[0] / dep.shape[0] * 100:.1f}%)")

