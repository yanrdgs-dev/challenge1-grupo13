"""EDA detalhada sobre campos avançados de Redes Sociais, Dinheiro Vivo, Ocupações, Destinação de Votos e Cotas FEFC."""

import polars as pl

print("Carregando bases...")
cand = pl.scan_parquet("data/processed/tse/candidatos").collect()
comp = pl.scan_parquet("data/processed/tse/candidatos_complementar").collect()
bens = pl.scan_parquet("data/processed/tse/bens").collect()
rede = pl.scan_parquet("data/processed/tse/redes_sociais").collect()

print("\n=== 1. REDES SOCIAIS E PRESENÇA DIGITAL ===")
print("Total de URLs cadastradas:", rede.shape[0])
print("Candidatos únicos com pelo menos 1 rede:", rede["SQ_CANDIDATO"].n_unique())

def detect_platform(url: str) -> str:
    if not url:
        return "Outros"
    u = url.lower()
    if "instagram.com" in u or "instagr.am" in u:
        return "Instagram"
    elif "facebook.com" in u or "fb.com" in u:
        return "Facebook"
    elif "twitter.com" in u or "x.com" in u:
        return "X (Twitter)"
    elif "youtube.com" in u or "youtu.be" in u:
        return "YouTube"
    elif "tiktok.com" in u:
        return "TikTok"
    elif "linkedin.com" in u:
        return "LinkedIn"
    elif "kwai" in u:
        return "Kwai"
    elif "threads.net" in u:
        return "Threads"
    elif "t.me" in u or "telegram" in u:
        return "Telegram"
    else:
        return "Site Próprio / Outros"

rede_platforms = rede.with_columns(
    pl.col("DS_URL").map_elements(detect_platform, return_dtype=pl.Utf8).alias("plataforma")
)
print("Distribuição por Plataforma Digital:")
print(rede_platforms["plataforma"].value_counts().sort("count", descending=True))

print("\n=== 2. DINHEIRO EM ESPÉCIE E BENS ESPECIAIS ===")
bens_dinheiro = bens.filter(pl.col("DS_TIPO_BEM_CANDIDATO").str.contains("Dinheiro em espécie"))
print("Total declarações de Dinheiro em Espécie:", bens_dinheiro.shape[0])
print("Volume total em Dinheiro Vivo (R$):", f"R$ {bens_dinheiro['VR_BEM_CANDIDATO'].sum():,.2f}")
print("Média por declaração de dinheiro:", f"R$ {bens_dinheiro['VR_BEM_CANDIDATO'].mean():,.2f}")
print("Mediana de dinheiro em espécie:", f"R$ {bens_dinheiro['VR_BEM_CANDIDATO'].median():,.2f}")
print("Maior valor em dinheiro vivo guardado:", f"R$ {bens_dinheiro['VR_BEM_CANDIDATO'].max():,.2f}")

top_dinheiro = (
    bens_dinheiro.filter(pl.col("ano") == 2022)
    .join(cand.filter(pl.col("ano") == 2022), on="SQ_CANDIDATO")
    .sort("VR_BEM_CANDIDATO", descending=True)
    .select(["NM_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "SG_UF", "DS_CARGO", "VR_BEM_CANDIDATO"])
    .head(5)
)
print("\nTop 5 Maiores Declarações de Dinheiro em Espécie (2022):")
print(top_dinheiro)

cripto = bens.filter(pl.col("DS_BEM_CANDIDATO").str.to_uppercase().str.contains("BITCOIN|CRIPTO|ETH|TETHER|USDT"))
print("\nDeclarações de Criptoativos:", cripto.shape[0], f"| Total R$: {cripto['VR_BEM_CANDIDATO'].sum():,.2f}")

aero = bens.filter(pl.col("DS_TIPO_BEM_CANDIDATO").str.contains("Aeronave") | pl.col("DS_BEM_CANDIDATO").str.to_uppercase().str.contains("HELICOPTERO|AERONAVE|AVIAO|JATINHO"))
print("Declarações de Aeronaves/Helicópteros:", aero.shape[0], f"| Total R$: {aero['VR_BEM_CANDIDATO'].sum():,.2f}")

print("\n=== 3. DESTINAÇÃO DOS VOTOS E INTEGRIDADE DA URNA ===")
print(comp["NM_TIPO_DESTINACAO_VOTOS"].value_counts().sort("count", descending=True))

sub_judice = comp.filter(pl.col("NM_TIPO_DESTINACAO_VOTOS").str.contains("sub judice"))
print("Candidatos sub judice no período:", sub_judice.shape[0])

print("\nInseridos na Urna (ST_CANDIDATO_INSERIDO_URNA):")
print(comp["ST_CANDIDATO_INSERIDO_URNA"].value_counts())

print("\nSituação do Candidato na Urna:")
print(comp["DS_SITUACAO_CANDIDATO_URNA"].value_counts().head(6))

print("\n=== 4. OCUPAÇÕES PROFISSIONAIS E IDADE NA POSSE ===")
idades = (
    comp.with_columns(pl.col("NR_IDADE_DATA_POSSE").cast(pl.Int32, strict=False))
    .filter((pl.col("NR_IDADE_DATA_POSSE") > 0) & (pl.col("NR_IDADE_DATA_POSSE") < 110))["NR_IDADE_DATA_POSSE"]
)
print("Estatísticas de Idade na Posse:")
print("Idade Mínima:", idades.min(), "| Média:", round(idades.mean(), 1), "| Mediana:", idades.median(), "| Máxima:", idades.max())

print("\nTop 10 Ocupações Declaradas (2022 Geral):")
print(cand.filter(pl.col("ano") == 2022)["DS_OCUPACAO"].value_counts().sort("count", descending=True).head(10))

print("\nNaturalidade - Candidatos concorrendo fora do estado de nascimento (2022):")
cand_2022 = cand.filter(pl.col("ano") == 2022).filter(pl.col("SG_UF").is_not_null())
mesmo_estado = cand_2022.filter(pl.col("SG_UF") == pl.col("SG_UF_NASCIMENTO")).shape[0]
outro_estado = cand_2022.filter((pl.col("SG_UF") != pl.col("SG_UF_NASCIMENTO")) & (pl.col("SG_UF") != "BR")).shape[0]
print(f"Candidatos no próprio estado natal: {mesmo_estado} ({mesmo_estado / (mesmo_estado + outro_estado) * 100:.1f}%)")
print(f"Candidatos em estado diferente do nascimento: {outro_estado} ({outro_estado / (mesmo_estado + outro_estado) * 100:.1f}%)")

print("\n=== 5. COTAS E REPASSES DO FUNDO ELEITORAL (FEFC) ===")
print("Gênero FEFC:", comp["DS_GENERO_FEFC"].value_counts().head(5))
print("Cor/Raça FEFC:", comp["DS_COR_RACA_FEFC"].value_counts().head(6))

print("\n=== 6. SUBSTITUIÇÃO DE CANDIDATURAS ===")
print("Candidatos Substituídos (ST_SUBSTITUIDO):", comp["ST_SUBSTITUIDO"].value_counts())

