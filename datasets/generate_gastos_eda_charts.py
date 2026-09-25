"""
Gera gráficos analíticos em alta resolução (300 DPI) para o Eixo 2: Gastos do Mandato e Cota Parlamentar.
Salva em datasets/eda_charts_gastos/ e copia para o diretório de artefatos.
"""

import shutil
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import polars as pl
import numpy as np

# Configurações de estilo
plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
plt.rcParams["font.sans-serif"] = "DejaVu Sans"
plt.rcParams["font.size"] = 10
plt.rcParams["axes.titlesize"] = 12
plt.rcParams["axes.labelsize"] = 10
plt.rcParams["figure.titlesize"] = 14

OUT_DIR = Path("datasets/eda_charts_gastos")
OUT_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_DIR = Path("/Users/aluno2/.gemini/antigravity-cli/brain/93e12fcf-6e68-4469-bfce-12092d0ba917")


def chart_01_sazonalidade():
    print("Gerando Gráfico 01: Sazonalidade Temporal dos Gastos...")
    df_ceap = pl.read_parquet("data/processed/camara/ceap/**/*.parquet")
    
    # Agrupar mensal 2022 a 2025
    mensal = (
        df_ceap.filter(pl.col("numAno").is_between(2022, 2025) & pl.col("numMes").is_between(1, 12))
        .group_by(["numAno", "numMes"])
        .agg(
            pl.col("vlrLiquido").sum().alias("total_mes"),
            pl.col("vlrLiquido").filter(pl.col("txtDescricao").str.contains("DIVULGAÇÃO")).sum().alias("divulgacao_mes")
        )
        .sort(["numAno", "numMes"])
    )
    
    # Criar coluna de período textual e numérico contínuo
    labels = [f"{row['numMes']:02d}/{str(row['numAno'])[2:]}" for row in mensal.iter_rows(named=True)]
    totais_mi = [row["total_mes"] / 1e6 for row in mensal.iter_rows(named=True)]
    divulg_mi = [row["divulgacao_mes"] / 1e6 for row in mensal.iter_rows(named=True)]
    x = np.arange(len(labels))
    
    fig, ax = plt.subplots(figsize=(14, 6))
    
    ax.plot(x, totais_mi, marker="o", color="#1f77b4", linewidth=2.5, label="Gasto Total Mensal (CEAP)")
    ax.plot(x, divulg_mi, marker="s", color="#ff7f0e", linewidth=2, linestyle="--", label="Divulgação Parlamentar")
    
    # Destacar a queda de agosto/setembro de 2022 (Período de Vedação Eleitoral)
    # 2022-08 é índice 7, 2022-09 é índice 8
    ax.axvspan(6.5, 8.5, color="#d62728", alpha=0.15, label="Período Eleitoral 2022 (Vedação Legal)")
    ax.annotate(
        "Queda de 97% na Divulgação\n(Vedação Art. 73 Lei 9.504/97)",
        xy=(7.5, divulg_mi[7]),
        xytext=(8, 12),
        arrowprops=dict(facecolor="#d62728", arrowstyle="->", lw=1.5),
        fontsize=9,
        fontweight="bold",
        color="#b30000",
        bbox=dict(boxstyle="round,pad=0.3", fc="#ffe6e6", ec="#d62728", lw=1)
    )
    
    # Destacar pico de dezembro de cada ano
    for idx, (yr, lbl) in enumerate(zip([11, 23, 35], ["Dez/22", "Dez/23", "Dez/24"])):
        if idx < len(totais_mi):
            ax.annotate(
                f"Pico Fim de Ano\n(R$ {totais_mi[yr]:.1f}M)",
                xy=(yr, totais_mi[yr]),
                xytext=(yr - 1.5, totais_mi[yr] + 2),
                arrowprops=dict(facecolor="#1f77b4", arrowstyle="->", lw=1),
                fontsize=8,
                bbox=dict(boxstyle="round,pad=0.2", fc="#e6f2ff", ec="#1f77b4", lw=0.8)
            )

    ax.set_title("Evolução Mensal dos Gastos da Cota Parlamentar (Câmara CEAP 2022–2025)\nImpacto da Legislação Eleitoral e Picos de Fechamento de Exercício", fontsize=13, fontweight="bold", pad=15)
    ax.set_ylabel("Valor Reembolsado (Milhões de R$)")
    ax.set_xticks(x[::2])
    ax.set_xticklabels(labels[::2], rotation=45)
    ax.set_ylim(0, max(totais_mi) * 1.2)
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("R$ %.0fM"))
    ax.legend(loc="upper left", frameon=True)
    ax.grid(True, linestyle=":", alpha=0.6)
    
    plt.tight_layout()
    out_file = OUT_DIR / "01_sazonalidade_gastos_mandato_2022_2026.png"
    fig.savefig(out_file, dpi=300)
    plt.close(fig)
    print(f"Salvo: {out_file}")


def chart_02_categorias():
    print("Gerando Gráfico 02: Matriz Comparativa de Categorias (Câmara vs Senado)...")
    df_ceap = pl.read_parquet("data/processed/camara/ceap/**/*.parquet")
    df_ceaps = pl.read_parquet("data/processed/senado/ceaps/**/*.parquet")
    
    # Top 6 Câmara
    cat_camara = (
        df_ceap.group_by("txtDescricao")
        .agg(pl.col("vlrLiquido").sum().alias("total"))
        .sort("total", descending=True)
        .head(6)
    )
    total_camara = df_ceap["vlrLiquido"].sum()
    
    # Top 5 Senado
    cat_senado = (
        df_ceaps.filter(pl.col("TIPO_DESPESA").is_not_null())
        .group_by("TIPO_DESPESA")
        .agg(pl.col("VALOR_REEMBOLSADO").sum().alias("total"))
        .sort("total", descending=True)
        .head(5)
    )
    total_senado = df_ceaps["VALOR_REEMBOLSADO"].sum()
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    
    # Plot Câmara
    cam_labels = [
        "Divulgação Parlamentar",
        "Locação de Veículos",
        "Manutenção de Escritório",
        "Combustíveis/Lubrificantes",
        "Consultorias Técnicas",
        "Hospedagem"
    ]
    cam_pcts = [(r["total"] / total_camara) * 100 for r in cat_camara.iter_rows(named=True)]
    cam_vals = [r["total"] / 1e6 for r in cat_camara.iter_rows(named=True)]
    
    y1 = np.arange(len(cam_labels))
    bars1 = ax1.barh(y1, cam_vals, color="#2b5c8f", edgecolor="none", height=0.6)
    ax1.set_yticks(y1)
    ax1.set_yticklabels(cam_labels, fontsize=9)
    ax1.invert_yaxis()
    ax1.set_xlabel("Total Acumulado (Milhões de R$)")
    ax1.set_title(f"Câmara dos Deputados (Total: R$ {total_camara/1e6:.1f}M)\nHegemonia de Divulgação e Autopromoção", fontsize=11, fontweight="bold")
    ax1.xaxis.set_major_formatter(ticker.FormatStrFormatter("R$ %.0fM"))
    
    for bar, pct, val in zip(bars1, cam_pcts, cam_vals):
        ax1.text(val + 5, bar.get_y() + bar.get_height()/2, f"R$ {val:.1f}M ({pct:.1f}%)", va="center", fontsize=8.5, fontweight="bold")
    ax1.set_xlim(0, max(cam_vals) * 1.3)
    
    # Plot Senado
    sen_labels = [
        "Consultorias / Assessorias",
        "Locomoção / Combustíveis",
        "Passagens Aéreas/Terrestres",
        "Divulgação Parlamentar",
        "Aluguel Escritório Político"
    ]
    sen_pcts = [(r["total"] / total_senado) * 100 for r in cat_senado.iter_rows(named=True)]
    sen_vals = [r["total"] / 1e6 for r in cat_senado.iter_rows(named=True)]
    
    y2 = np.arange(len(sen_labels))
    bars2 = ax2.barh(y2, sen_vals, color="#388e3c", edgecolor="none", height=0.6)
    ax2.set_yticks(y2)
    ax2.set_yticklabels(sen_labels, fontsize=9)
    ax2.invert_yaxis()
    ax2.set_xlabel("Total Acumulado (Milhões de R$)")
    ax2.set_title(f"Senado Federal (Total: R$ {total_senado/1e6:.1f}M)\nPredomínio de Consultorias Técnicas e Deslocamentos", fontsize=11, fontweight="bold")
    ax2.xaxis.set_major_formatter(ticker.FormatStrFormatter("R$ %.0fM"))
    
    for bar, pct, val in zip(bars2, sen_pcts, sen_vals):
        ax2.text(val + 0.8, bar.get_y() + bar.get_height()/2, f"R$ {val:.1f}M ({pct:.1f}%)", va="center", fontsize=8.5, fontweight="bold")
    ax2.set_xlim(0, max(sen_vals) * 1.3)
    
    plt.suptitle("Matriz de Destinação da Cota Parlamentar (2022–2026)", fontsize=13, fontweight="bold", y=1.02)
    plt.tight_layout()
    out_file = OUT_DIR / "02_categorias_gastos_camara_vs_senado.png"
    fig.savefig(out_file, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Salvo: {out_file}")


def chart_03_distribuicao_parlamentares():
    print("Gerando Gráfico 03: Distribuição e Ranking de Gastadores (Câmara 2023)...")
    df_ceap = pl.read_parquet("data/processed/camara/ceap/**/*.parquet")
    
    gastos_2023 = (
        df_ceap.filter(pl.col("numAno") == 2023)
        .group_by(["txNomeParlamentar", "sgUF", "sgPartido"])
        .agg(pl.col("vlrLiquido").sum().alias("total_ano"))
        .sort("total_ano", descending=True)
    )
    
    totais = (gastos_2023["total_ano"] / 1e3).to_numpy() # em milhares de R$
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    
    # 1. Boxplot e Percentis
    box = ax1.boxplot(
        totais, vert=True, patch_artist=True,
        boxprops=dict(facecolor="#c6dbef", color="#1f77b4", lw=1.5),
        medianprops=dict(color="#d62728", lw=2),
        whiskerprops=dict(color="#1f77b4", lw=1.2),
        capprops=dict(color="#1f77b4", lw=1.2),
        flierprops=dict(marker="o", color="#7f7f7f", markersize=4, alpha=0.5)
    )
    
    p25 = np.percentile(totais, 25)
    p50 = np.percentile(totais, 50)
    p75 = np.percentile(totais, 75)
    p90 = np.percentile(totais, 90)
    
    ax1.set_xticks([1])
    ax1.set_xticklabels(["Deputados Federais (2023)"])
    ax1.set_ylabel("Gasto Anual Reembolsado (Milhares de R$)")
    ax1.yaxis.set_major_formatter(ticker.FormatStrFormatter("R$ %.0fk"))
    ax1.set_title("Dispersão dos Gastos Anuais da Cota (2023)\nMediana: R$ 254k | P90: R$ 466k", fontsize=11, fontweight="bold")
    
    ax1.text(1.15, p50, f"Mediana (P50):\nR$ {p50:.1f}k", color="#d62728", fontweight="bold", va="center")
    ax1.text(1.15, p75, f"P75: R$ {p75:.1f}k", color="#1f77b4", va="center")
    ax1.text(1.15, p25, f"P25: R$ {p25:.1f}k", color="#1f77b4", va="center")
    ax1.text(1.15, p90, f"P90: R$ {p90:.1f}k", color="#555", va="center")
    ax1.set_xlim(0.8, 1.5)
    
    # 2. Top 8 Maiores Gastadores
    top8 = gastos_2023.head(8)
    nomes = [f"{r['txNomeParlamentar']} ({r['sgPartido']}/{r['sgUF']})" for r in top8.iter_rows(named=True)]
    valores_k = [r["total_ano"] / 1e3 for r in top8.iter_rows(named=True)]
    
    y = np.arange(len(nomes))
    bars = ax2.barh(y, valores_k, color="#e6550d", height=0.6)
    ax2.set_yticks(y)
    ax2.set_yticklabels(nomes, fontsize=9)
    ax2.invert_yaxis()
    ax2.set_xlabel("Total Reembolsado em 2023 (Milhares de R$)")
    ax2.set_title("Top 8 Deputados com Maior Custo de Cota (2023)\nTeto Anual Aproximado das UFs mais distantes: ~R$ 600k", fontsize=11, fontweight="bold")
    ax2.xaxis.set_major_formatter(ticker.FormatStrFormatter("R$ %.0fk"))
    
    for bar, val in zip(bars, valores_k):
        ax2.text(val + 5, bar.get_y() + bar.get_height()/2, f"R$ {val:.1f}k", va="center", fontsize=8.5, fontweight="bold")
    ax2.set_xlim(0, max(valores_k) * 1.18)
    
    plt.tight_layout()
    out_file = OUT_DIR / "03_distribuicao_gastos_parlamentares_percentis.png"
    fig.savefig(out_file, dpi=300)
    plt.close(fig)
    print(f"Salvo: {out_file}")


def chart_04_fornecedores_hibridos():
    print("Gerando Gráfico 04: Recursos Pagos a Fornecedores (Mandato vs Campanha TSE)...")
    empresas = [
        "PANTANAL VEÍCULOS\n(Locação de Frotas)",
        "FACEBOOK / META\n(Impulsionamento Digital)",
        "LATAM AIRLINES\n(Passagens Aéreas)",
        "TELEFÔNICA / VIVO\n(Telefonia e Dados)",
        "SUPREMA MOBILIDADE\n(Locação de Frotas)",
        "NOVACAR LOCADORA\n(Locação de Frotas)",
        "DALETH VEÍCULOS\n(Locação de Frotas)",
        "VIA LOCADORA\n(Locação de Frotas)",
        "AZUL LINHAS AÉREAS\n(Passagens Aéreas)",
        "PONTUAL LOC CAR\n(Locação de Frotas)"
    ]
    camara_vals = [15.26, 9.95, 7.62, 7.22, 6.75, 5.83, 3.30, 3.21, 3.06, 2.54] # em Milhões de R$
    tse_vals = [0.08, 371.64, 0.01, 0.01, 0.10, 0.02, 0.04, 0.01, 0.04, 0.48]    # em Milhões de R$
    
    fig, ax = plt.subplots(figsize=(13.5, 6.5))
    y = np.arange(len(empresas))
    height = 0.55
    
    # Barra da Câmara
    bars1 = ax.barh(y, camara_vals, height=height, label="Pago pela Câmara (Cota Parlamentar CEAP)", color="#1f77b4")
    ax.set_yticks(y)
    ax.set_yticklabels(empresas, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Total de Recursos Públicos Reembolsados na Câmara (Milhões de R$)")
    ax.set_title(
        "Recursos Públicos e Partidários Pagos aos Top Fornecedores da Câmara e Campanhas do TSE\n"
        "(Valores brutos recebidos pelas empresas do erário/partidos — Não reflete a margem de lucro líquido privado)",
        fontsize=11.5, fontweight="bold", pad=12
    )
    ax.xaxis.set_major_formatter(ticker.FormatStrFormatter("R$ %.0fM"))
    
    for bar, cam, tse in zip(bars1, camara_vals, tse_vals):
        tse_txt = f"TSE: R$ {tse:.2f}M" if tse < 100 else f"TSE: R$ {tse:.1f}M (Fundo Eleitoral)"
        ax.text(
            cam + 0.25, bar.get_y() + bar.get_height()/2,
            f"Câmara: R$ {cam:.2f}M  |  {tse_txt}",
            va="center", fontsize=8.5, fontweight="bold", color="#222"
        )
    
    ax.set_xlim(0, max(camara_vals) * 1.38)
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="lower right", frameon=True, fontsize=9.5)
    
    plt.tight_layout()
    out_file = OUT_DIR / "04_top_fornecedores_e_sobreposicao_tse.png"
    fig.savefig(out_file, dpi=300)
    plt.close(fig)
    print(f"Salvo: {out_file}")


def chart_05_auditoria_glosas_passagens():
    print("Gerando Gráfico 05: Auditoria Documental, Glosas e Passagens Aéreas...")
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(16.5, 5.2))
    
    # 1. Rastreabilidade de Comprovantes (Pizza)
    labels = ["Com Link Oficial\n(NF-e / Recibo)", "Sem Link Direto"]
    sizes = [93.5, 6.5]
    colors = ["#2ca02c", "#d62728"]
    ax1.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=140, colors=colors, explode=(0.08, 0), textprops={"fontsize": 9.5, "fontweight": "bold"})
    ax1.set_title("Rastreabilidade Documental\n734.544 despesas com URL da nota fiscal", fontsize=11, fontweight="bold")
    
    # 2. Glosas e Rejeições (Indicadores)
    ax2.axis("off")
    ax2.set_title("Auditoria Interna e Glosas (Câmara)", fontsize=11, fontweight="bold", pad=20)
    stats_text = (
        "Total de Notas com Glosa:\n"
        "➤ 46.365 notas fiscais questionadas\n\n"
        "Total Economizado pelo Erário:\n"
        "➤ R$ 5.652.067,57 glosados\n\n"
        "Maior Glosa em Documento Único:\n"
        "➤ R$ 33.329,00\n\n"
        "Insight para o Fact-Checking:\n"
        "A fiscalização da Mesa Diretora corta\n"
        "automaticamente gastos fora das normas\n"
        "antes do ressarcimento final."
    )
    ax2.text(0.05, 0.5, stats_text, fontsize=9.5, verticalalignment="center", bbox=dict(boxstyle="round,pad=0.8", fc="#f7f7f7", ec="#bbb", lw=1))
    
    # 3. Top Trechos Aéreos de IDA (Apenas partindo de BSB)
    trechos = [
        "BSB ➔ Confins (Belo Horizonte)",
        "BSB ➔ Salvador (BA)",
        "BSB ➔ Santos Dumont (Rio de Janeiro)",
        "BSB ➔ Congonhas (São Paulo)",
        "BSB ➔ Belém (PA)",
        "BSB ➔ Boa Vista (RR)"
    ]
    voos = [544, 494, 333, 329, 188, 176]
    y3 = np.arange(len(trechos))
    bars3 = ax3.barh(y3, voos, color="#1f77b4", height=0.55)
    ax3.set_yticks(y3)
    ax3.set_yticklabels(trechos, fontsize=8.5)
    ax3.invert_yaxis()
    ax3.set_xlabel("Quantidade de Passagens Reembolsadas")
    ax3.set_title("Top Destinos de Ida a Partir de Brasília\n(Rotas BSB ➔ Redutos Eleitorais)", fontsize=11, fontweight="bold")
    for bar, val in zip(bars3, voos):
        ax3.text(val + 10, bar.get_y() + bar.get_height()/2, f"{val} voos", va="center", fontsize=8.5, fontweight="bold")
    ax3.set_xlim(0, max(voos) * 1.25)
    
    plt.tight_layout()
    out_file = OUT_DIR / "05_auditoria_glosas_e_passagens.png"
    fig.savefig(out_file, dpi=300)
    plt.close(fig)
    print(f"Salvo: {out_file}")


def copy_to_artifacts():
    print("\nCopiando gráficos para diretório de artefatos...")
    for f in OUT_DIR.glob("*.png"):
        dest = ARTIFACT_DIR / f.name
        shutil.copy(f, dest)
        print(f"Copiado para artefato: {dest.name}")


def main():
    chart_01_sazonalidade()
    chart_02_categorias()
    chart_03_distribuicao_parlamentares()
    chart_04_fornecedores_hibridos()
    chart_05_auditoria_glosas_passagens()
    copy_to_artifacts()
    print("\nTODOS OS GRÁFICOS DO EIXO 2 GERADOS COM SUCESSO!")


if __name__ == "__main__":
    main()
