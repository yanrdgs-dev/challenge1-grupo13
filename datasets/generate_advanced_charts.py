"""Gera gráficos analíticos dos campos avançados (Redes Sociais, Dinheiro Vivo, Bens Especiais)."""

import os
import polars as pl
import numpy as np
import matplotlib.pyplot as plt

output_dir = "datasets/eda_charts_tse"
os.makedirs(output_dir, exist_ok=True)

plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams['font.sans-serif'] = 'Helvetica, Arial, DejaVu Sans'

# -------------------------------------------------------------
# GRÁFICO 6: Plataformas de Redes Sociais Declaradas
# -------------------------------------------------------------
print("Gerando Gráfico 6: Plataformas de Redes Sociais...")
rede = pl.scan_parquet("data/processed/tse/redes_sociais").collect()

def detect_platform(url: str) -> str:
    if not url: return "Outros"
    u = url.lower()
    if "instagram.com" in u or "instagr.am" in u: return "Instagram"
    elif "facebook.com" in u or "fb.com" in u: return "Facebook"
    elif "tiktok.com" in u: return "TikTok"
    elif "youtube.com" in u or "youtu.be" in u: return "YouTube"
    elif "twitter.com" in u or "x.com" in u: return "X (Twitter)"
    elif "kwai" in u: return "Kwai"
    elif "threads.net" in u: return "Threads"
    elif "linkedin.com" in u: return "LinkedIn"
    elif "telegram" in u or "t.me" in u: return "Telegram"
    else: return "Site / Outros"

rede_platforms = (
    rede.with_columns(pl.col("DS_URL").map_elements(detect_platform, return_dtype=pl.Utf8).alias("plataforma"))
    ["plataforma"].value_counts().sort("count", descending=True)
)

fig, ax = plt.subplots(figsize=(10, 5.5), dpi=300)
y_pos = np.arange(len(rede_platforms))
counts = rede_platforms["count"].to_numpy()
counts_k = counts / 1e3
labels = rede_platforms["plataforma"].to_list()
colors = ['#E1306C', '#4267B2', '#7f8c8d', '#000000', '#FF0000', '#1DA1F2', '#FF6600', '#333333', '#0077B5', '#229ED9']

bars = ax.barh(y_pos, counts_k, color=colors, edgecolor='black', alpha=0.85)
ax.set_yticks(y_pos)
ax.set_yticklabels(labels)
ax.invert_yaxis()
ax.set_xlabel("Quantidade de Contas Cadastradas (Milhares)")
ax.set_title("Presença Digital Oficial dos Candidatos - TSE 2022–2026\n(Total: ~1 Milhão de URLs Homologadas)", fontweight='bold', pad=12)

total_urls = counts.sum()
for bar in bars:
    w = bar.get_width()
    pct = (w * 1e3 / total_urls) * 100
    ax.text(w + 5, bar.get_y() + bar.get_height()/2, f"{w:,.1f}k ({pct:.1f}%)",
            ha='left', va='center', fontsize=9, fontweight='semibold')

ax.set_xlim(0, max(counts_k) * 1.18)
plt.tight_layout()
fig.savefig(f"{output_dir}/06_redes_sociais_plataformas.png")
plt.close(fig)

# -------------------------------------------------------------
# GRÁFICO 7: Bens Especiais (Dinheiro Vivo, Cripto, Aeronaves)
# -------------------------------------------------------------
print("Gerando Gráfico 7: Bens Especiais...")
bens = pl.scan_parquet("data/processed/tse/bens").collect()

bens_dinheiro = bens.filter(pl.col("DS_TIPO_BEM_CANDIDATO").str.contains("Dinheiro em espécie"))
cripto = bens.filter(pl.col("DS_BEM_CANDIDATO").str.to_uppercase().str.contains("BITCOIN|CRIPTO|ETH|TETHER|USDT"))
aero = bens.filter(pl.col("DS_TIPO_BEM_CANDIDATO").str.contains("Aeronave") | pl.col("DS_BEM_CANDIDATO").str.to_uppercase().str.contains("HELICOPTERO|AERONAVE|AVIAO|JATINHO"))

categorias = ["Dinheiro Vivo\n(em Espécie)", "Criptoativos\n(Bitcoin/Tokens)", "Aeronaves e\nHelicópteros"]
totais_bi = [bens_dinheiro["VR_BEM_CANDIDATO"].sum() / 1e9, cripto["VR_BEM_CANDIDATO"].sum() / 1e9, aero["VR_BEM_CANDIDATO"].sum() / 1e9]
qtd_ocorrencias = [bens_dinheiro.shape[0], cripto.shape[0], aero.shape[0]]

fig, ax1 = plt.subplots(figsize=(8.5, 5), dpi=300)

x = np.arange(len(categorias))
width = 0.4

bars1 = ax1.bar(x - width/2, totais_bi, width, label='Volume Total (R$ Bilhões)', color='#27ae60', edgecolor='black', alpha=0.85)
ax1.set_ylabel('R$ Bilhões', color='#27ae60', fontweight='bold')
ax1.tick_params(axis='y', labelcolor='#27ae60')

ax2 = ax1.twinx()
bars2 = ax2.bar(x + width/2, qtd_ocorrencias, width, label='Qtd. Declarações', color='#2980b9', edgecolor='black', alpha=0.85)
ax2.set_ylabel('Quantidade de Declarações', color='#2980b9', fontweight='bold')
ax2.tick_params(axis='y', labelcolor='#2980b9')

ax1.set_xticks(x)
ax1.set_xticklabels(categorias, fontweight='semibold')
ax1.set_title("Bens de Interesse Investigativo Declarados no TSE (2022–2026)", fontweight='bold', pad=15)

for b in bars1:
    h = b.get_height()
    ax1.text(b.get_x() + b.get_width()/2, h + 0.05, f"R$ {h:.2f} bi", ha='center', va='bottom', fontsize=9, fontweight='bold', color='#27ae60')

for b in bars2:
    h = b.get_height()
    ax2.text(b.get_x() + b.get_width()/2, h + 1000, f"{h:,} itens", ha='center', va='bottom', fontsize=9, fontweight='bold', color='#2980b9')

ax1.set_ylim(0, max(totais_bi) * 1.25)
ax2.set_ylim(0, max(qtd_ocorrencias) * 1.2)
plt.tight_layout()
fig.savefig(f"{output_dir}/07_bens_especiais_investigativos.png")
plt.close(fig)

print("✓ Gráficos 6 e 7 gerados com sucesso!")
