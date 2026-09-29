"""Gera gráficos informativos e de alta qualidade para a EDA de Candidaturas e Bens (TSE 2022-2026)."""

import os
import polars as pl
import numpy as np
import matplotlib.pyplot as plt
import unicodedata

# Diretório de saída
output_dir = "datasets/eda_charts_tse"
os.makedirs(output_dir, exist_ok=True)

# Estilização padrão
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams['font.sans-serif'] = 'Helvetica, Arial, DejaVu Sans'
plt.rcParams['font.size'] = 10
plt.rcParams['axes.titlesize'] = 13
plt.rcParams['axes.labelsize'] = 11

print("Carregando bases para plotagem...")
cand = pl.scan_parquet("data/processed/tse/candidatos").collect()
bens = pl.scan_parquet("data/processed/tse/bens").collect()
dep = pl.scan_parquet("data/processed/camara/deputados.parquet").collect()

# -------------------------------------------------------------
# GRÁFICO 1: Distribuição de Patrimônio e Linhas de Percentis
# -------------------------------------------------------------
print("Gerando Gráfico 1: Distribuição de Patrimônio...")
bens_cand = (
    bens.group_by(["ano", "SQ_CANDIDATO"])
    .agg(pl.sum("VR_BEM_CANDIDATO").alias("patrimonio_total"))
    .filter(pl.col("patrimonio_total") > 0)
)

valores = bens_cand["patrimonio_total"].to_numpy()
log_vals = np.log10(valores)

fig, ax = plt.subplots(figsize=(10, 5), dpi=300)
n, bins, patches = ax.hist(log_vals, bins=60, color='#1f77b4', edgecolor='black', alpha=0.75)

# Linhas verticais para percentis
percentis = {
    'P25 (R$ 32k)': np.log10(32000),
    'Mediana (R$ 122,5k)': np.log10(122562),
    'P75 (R$ 345k)': np.log10(345432),
    'P90 (R$ 813k)': np.log10(813000),
    'P95 (R$ 1,4M)': np.log10(1400000),
    'P99 (R$ 4,6M)': np.log10(4664050),
}
colors = ['#2ca02c', '#d62728', '#ff7f0e', '#9467bd', '#8c564b', '#e377c2']

for (label, val), col in zip(percentis.items(), colors):
    ax.axvline(val, color=col, linestyle='--', linewidth=1.6, label=label)

ax.set_title("Distribuição do Patrimônio Declarado por Candidato (TSE 2022–2026)", fontweight='bold', pad=12)
ax.set_xlabel("Patrimônio Total Declarado (Escala Logarítmica)")
ax.set_ylabel("Quantidade de Candidatos")

# Custom ticks para escala logarítmica
ticks = [3, 4, 5, 6, 7, 8, 9]
labels = ["R$ 1 mil", "R$ 10 mil", "R$ 100 mil", "R$ 1 milhão", "R$ 10 mi", "R$ 100 mi", "R$ 1 bi"]
ax.set_xticks(ticks)
ax.set_xticklabels(labels)
ax.legend(title="Percentis Chave", frameon=True, facecolor='white', framealpha=0.9)
plt.tight_layout()
fig.savefig(f"{output_dir}/01_distribuicao_patrimonio_percentis.png")
plt.close(fig)

# -------------------------------------------------------------
# GRÁFICO 2: Top 10 Maiores Patrimônios Declarados em 2022
# -------------------------------------------------------------
print("Gerando Gráfico 2: Top 10 Maiores Patrimônios...")
top_10 = (
    bens_cand.filter(pl.col("ano") == 2022)
    .join(cand.filter(pl.col("ano") == 2022), on="SQ_CANDIDATO")
    .sort("patrimonio_total", descending=True)
    .head(10)
)

nomes = [f"{r['NM_URNA_CANDIDATO']} ({r['SG_PARTIDO']}-{r['SG_UF']})" for r in top_10.to_dicts()]
valores_mi = [r['patrimonio_total'] / 1e6 for r in top_10.to_dicts()]

fig, ax = plt.subplots(figsize=(10, 6), dpi=300)
y_pos = np.arange(len(nomes))
bars = ax.barh(y_pos, valores_mi, color='#2b5c8f', edgecolor='black', alpha=0.85)

ax.set_yticks(y_pos)
ax.set_yticklabels(nomes)
ax.invert_yaxis()
ax.set_xlabel("Patrimônio Total Declarado (R$ Milhões)")
ax.set_title("Top 10 Maiores Patrimônios Declarados - Eleições Gerais 2022", fontweight='bold', pad=12)

# Rótulos nas barras
for bar in bars:
    width = bar.get_width()
    ax.text(width + 15, bar.get_y() + bar.get_height()/2, f"R$ {width:,.1f}M",
            ha='left', va='center', fontsize=9, fontweight='semibold', color='#333333')

ax.set_xlim(0, max(valores_mi) * 1.15)
plt.tight_layout()
fig.savefig(f"{output_dir}/02_top_patrimonios_2022.png")
plt.close(fig)

# -------------------------------------------------------------
# GRÁFICO 3: Perfil Sociodemográfico das Candidaturas 2022
# -------------------------------------------------------------
print("Gerando Gráfico 3: Perfil Sociodemográfico...")
cand_2022 = cand.filter(pl.col("ano") == 2022)

fig, axes = plt.subplots(1, 3, figsize=(15, 5), dpi=300)

# Gênero
gen = cand_2022.filter(pl.col("DS_GENERO").is_in(["MASCULINO", "FEMININO"]))["DS_GENERO"].value_counts()
axes[0].pie(gen["count"], labels=gen["DS_GENERO"], autopct='%1.1f%%', colors=['#4a90e2', '#e94e77'], startangle=90, wedgeprops=dict(edgecolor='white', linewidth=2))
axes[0].set_title("Distribuição por Gênero", fontweight='bold')

# Cor / Raça
raca = cand_2022.filter(pl.col("DS_COR_RACA").is_in(["BRANCA", "PARDA", "PRETA", "AMARELA", "INDÍGENA"]))["DS_COR_RACA"].value_counts().sort("count", descending=True)
bars_raca = axes[1].bar(raca["DS_COR_RACA"], raca["count"], color='#50b848', edgecolor='black', alpha=0.8)
axes[1].set_title("Autodeclaração de Cor/Raça", fontweight='bold')
axes[1].set_ylabel("Quantidade de Candidatos")
axes[1].tick_params(axis='x', rotation=30)
for b in bars_raca:
    h = b.get_height()
    axes[1].text(b.get_x() + b.get_width()/2, h + 200, f"{h/len(cand_2022)*100:.1f}%", ha='center', fontsize=8)

# Escolaridade
esc = cand_2022.filter(pl.col("DS_GRAU_INSTRUCAO").is_not_null())["DS_GRAU_INSTRUCAO"].value_counts().sort("count", descending=True).head(4)
axes[2].barh(esc["DS_GRAU_INSTRUCAO"], esc["count"], color='#f39c12', edgecolor='black', alpha=0.8)
axes[2].set_title("Top Graus de Escolaridade", fontweight='bold')
axes[2].set_xlabel("Quantidade")
axes[2].invert_yaxis()

plt.suptitle("Perfil Sociodemográfico dos Candidatos - TSE 2022", fontsize=15, fontweight='bold', y=1.02)
plt.tight_layout()
fig.savefig(f"{output_dir}/03_perfil_sociodemografico_2022.png")
plt.close(fig)

# -------------------------------------------------------------
# GRÁFICO 4: Patrimônio Eleitos vs Não Eleitos (Deputados Federais)
# -------------------------------------------------------------
print("Gerando Gráfico 4: Patrimônio Eleitos vs Não Eleitos...")
df_dep_fed = (
    cand.filter((pl.col("ano") == 2022) & (pl.col("DS_CARGO") == "DEPUTADO FEDERAL"))
    .join(bens_cand.filter(pl.col("ano") == 2022), on="SQ_CANDIDATO", how="left")
    .with_columns(
        pl.col("patrimonio_total").fill_null(0.0),
        pl.when(pl.col("DS_SIT_TOT_TURNO").str.contains("ELEITO")).then(pl.lit("Eleitos (513)")).otherwise(pl.lit("Não Eleitos")).alias("status_eleicao")
    )
)

stats = df_dep_fed.group_by("status_eleicao").agg([
    (pl.mean("patrimonio_total") / 1e3).alias("media_milhares"),
    (pl.median("patrimonio_total") / 1e3).alias("mediana_milhares"),
])

fig, ax = plt.subplots(figsize=(8, 5), dpi=300)
x = np.arange(len(stats))
width = 0.35

rects1 = ax.bar(x - width/2, stats["media_milhares"], width, label='Média (R$ Mil)', color='#34495e', edgecolor='black')
rects2 = ax.bar(x + width/2, stats["mediana_milhares"], width, label='Mediana (R$ Mil)', color='#1abc9c', edgecolor='black')

ax.set_ylabel('R$ (Milhares)')
ax.set_title('Comparativo Patrimonial: Deputados Federais Eleitos vs Não Eleitos (2022)', fontweight='bold', pad=12)
ax.set_xticks(x)
ax.set_xticklabels(stats["status_eleicao"])
ax.legend(frameon=True)

for rect in rects1:
    h = rect.get_height()
    ax.annotate(f'R$ {h:,.0f}k', xy=(rect.get_x() + rect.get_width()/2, h), xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontweight='bold')
for rect in rects2:
    h = rect.get_height()
    ax.annotate(f'R$ {h:,.0f}k', xy=(rect.get_x() + rect.get_width()/2, h), xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontweight='bold')

plt.tight_layout()
fig.savefig(f"{output_dir}/04_patrimonio_eleitos_vs_nao_eleitos.png")
plt.close(fig)

# -------------------------------------------------------------
# GRÁFICO 5: Resolução de Entidades (Entity Matching)
# -------------------------------------------------------------
print("Gerando Gráfico 5: Resolução de Entidades...")
def strip_accents(s: str) -> str:
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").upper().strip()

dep_57 = dep.filter(pl.col("idLegislaturaFinal") >= 57).with_columns([
    pl.col("nomeCivil").map_elements(strip_accents, return_dtype=pl.Utf8).alias("nome_norm")
])
cand_2022 = cand.filter(pl.col("ano") == 2022).with_columns([
    pl.col("NM_CANDIDATO").map_elements(strip_accents, return_dtype=pl.Utf8).alias("nome_norm")
])

matches = dep_57.join(cand_2022, on="nome_norm", how="inner")["nome_norm"].n_unique()
total_dep = dep_57.shape[0]
nao_match = total_dep - matches

fig, ax = plt.subplots(figsize=(7, 5), dpi=300)
sizes = [matches, nao_match]
labels = [f"Match Exato no TSE\n({matches} parlamentares - 96.6%)", f"Variação / Suplente Tardio\n({nao_match} parlamentares - 3.4%)"]
colors = ['#27ae60', '#e74c3c']

wedges, texts, autotexts = ax.pie(
    sizes, labels=labels, autopct='%1.1f%%',
    startangle=140, colors=colors, explode=(0.08, 0),
    wedgeprops=dict(edgecolor='white', linewidth=2)
)
for t in autotexts:
    t.set_fontsize(11)
    t.set_weight('bold')
    t.set_color('white')

ax.set_title("Viabilidade da Resolução de Entidades:\nCâmara dos Deputados (57ª Leg.) vs Candidatos TSE (2022)", fontweight='bold', pad=15)
plt.tight_layout()
fig.savefig(f"{output_dir}/05_entity_matching_resolucao_entidades.png")
plt.close(fig)

print(f"\n✓ Todos os 5 gráficos foram salvos com sucesso em: {output_dir}")
