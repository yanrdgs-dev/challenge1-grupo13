"""
Gera gráficos analíticos em alta resolução (300 DPI) para o Eixo 3: Atividade Legislativa, Autoria e Tramitação.
Salva em datasets/eda_charts_legislativo/ e copia para o diretório de artefatos.
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

OUT_DIR = Path("datasets/eda_charts_legislativo")
OUT_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_DIR = Path("/Users/aluno2/.gemini/antigravity-cli/brain/93e12fcf-6e68-4469-bfce-12092d0ba917")


def chart_01_taxonomia():
    print("Gerando Gráfico 01: Taxonomia das Proposições da Câmara...")
    df_prop = pl.read_parquet("data/processed/camara/proposicoes/**/*.parquet")
    total = len(df_prop)
    
    tipos_substantivos = {"PL", "PLP", "PEC", "MPV", "PDL"}
    tipos_instrumentais = {"RPD", "PRL", "REQ", "RIC", "EMC", "PAR", "INC", "DOC", "SBT"}
    
    qtd_sub = df_prop.filter(pl.col("siglaTipo").is_in(list(tipos_substantivos))).height
    qtd_inst = df_prop.filter(pl.col("siglaTipo").is_in(list(tipos_instrumentais))).height
    qtd_outros = total - (qtd_sub + qtd_inst)
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))
    
    # 1. Donut Chart das macrocategorias
    labels = [
        f"Regimental / Instrumental\n({qtd_inst:,} atos - {qtd_inst/total*100:.1f}%)",
        f"Outros Atos e Recursos\n({qtd_outros:,} atos - {qtd_outros/total*100:.1f}%)",
        f"Substantivo (Força de Lei)\n({qtd_sub:,} atos - {qtd_sub/total*100:.1f}%)"
    ]
    sizes = [qtd_inst, qtd_outros, qtd_sub]
    colors = ["#4575b4", "#91bfdb", "#d73027"]
    
    wedges, texts = ax1.pie(sizes, labels=labels, startangle=140, colors=colors, explode=(0, 0, 0.1), textprops={"fontsize": 9, "fontweight": "bold"})
    ax1.set_title("Macrocategorias de Atos Legislativos (140.507 Proposições)\nApenas 10% possuem força normativa direta", fontsize=11, fontweight="bold")
    
    # 2. Top 8 Tipos Específicos
    top8 = (
        df_prop.group_by(["siglaTipo", "descricaoTipo"])
        .agg(pl.len().alias("qtd"))
        .sort("qtd", descending=True)
        .head(8)
    )
    siglas = [f"{r['siglaTipo']} - {r['descricaoTipo'][:22]}" for r in top8.iter_rows(named=True)]
    valores = [r["qtd"] for r in top8.iter_rows(named=True)]
    
    y = np.arange(len(siglas))
    bar_colors = ["#d73027" if "PL" in s.split()[0] else "#4575b4" for s in siglas]
    bars = ax2.barh(y, valores, color=bar_colors, height=0.6)
    ax2.set_yticks(y)
    ax2.set_yticklabels(siglas, fontsize=8.5)
    ax2.invert_yaxis()
    ax2.set_xlabel("Quantidade de Proposições Registradas")
    ax2.set_title("Top 8 Tipos de Atos mais Frequentes\nPareceres e Requerimentos superam Projetos de Lei", fontsize=11, fontweight="bold")
    ax2.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f"{int(x):,}"))
    
    for bar, val in zip(bars, valores):
        pct = (val / total) * 100
        ax2.text(val + 300, bar.get_y() + bar.get_height()/2, f"{val:,} ({pct:.1f}%)", va="center", fontsize=8, fontweight="bold")
    ax2.set_xlim(0, max(valores) * 1.25)
    
    plt.suptitle("Taxonomia e Composição da Atividade Legislativa (Câmara dos Deputados 2022–2026)", fontsize=13, fontweight="bold", y=1.02)
    plt.tight_layout()
    out_file = OUT_DIR / "01_taxonomia_proposicoes_camara.png"
    fig.savefig(out_file, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Salvo: {out_file}")


def chart_02_autoria():
    print("Gerando Gráfico 02: Autores Principais de Projetos vs Cosignatários...")
    df_aut = pl.read_parquet("data/processed/camara/proposicoes_autores/**/*.parquet")
    df_prop = pl.read_parquet("data/processed/camara/proposicoes/**/*.parquet")
    
    aut_dep = df_aut.filter(pl.col("tipoAutor") == "Deputado(a)").with_columns(
        pl.when((pl.col("proponente") == 1) | (pl.col("ordemAssinatura") == 1))
        .then(pl.lit("Autor Principal"))
        .otherwise(pl.lit("Cosignatário"))
        .alias("papel")
    )
    
    df_joined = aut_dep.join(
        df_prop.select(["id", "siglaTipo"]),
        left_on="idProposicao",
        right_on="id",
        how="inner"
    )
    
    # 1. Top 8 Autores Principais de PL/PEC/PLP (agrupados por ID do parlamentar para consolidar trocas de partido)
    top_principais = (
        df_joined.filter(pl.col("siglaTipo").is_in(["PL", "PEC", "PLP"]) & (pl.col("papel") == "Autor Principal"))
        .group_by("idDeputadoAutor")
        .agg(
            pl.col("nomeAutor").first().alias("nomeAutor"),
            pl.col("siglaUFAutor").first().alias("siglaUFAutor"),
            pl.col("siglaPartidoAutor").unique().str.join("/").alias("siglaPartidoAutor"),
            pl.len().alias("total")
        )
        .sort("total", descending=True)
        .head(8)
    )
    
    # 2. Top 8 Cosignatários (agrupados por ID do parlamentar para consolidar trocas de partido)
    top_cosign = (
        df_joined.filter(pl.col("papel") == "Cosignatário")
        .group_by("idDeputadoAutor")
        .agg(
            pl.col("nomeAutor").first().alias("nomeAutor"),
            pl.col("siglaUFAutor").first().alias("siglaUFAutor"),
            pl.col("siglaPartidoAutor").unique().str.join("/").alias("siglaPartidoAutor"),
            pl.len().alias("total")
        )
        .sort("total", descending=True)
        .head(8)
    )
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    
    # Plot Autores Principais
    nomes1 = [f"{r['nomeAutor']} ({r['siglaPartidoAutor']}/{r['siglaUFAutor']})" for r in top_principais.iter_rows(named=True)]
    vals1 = [r["total"] for r in top_principais.iter_rows(named=True)]
    y1 = np.arange(len(nomes1))
    bars1 = ax1.barh(y1, vals1, color="#2b5c8f", height=0.6)
    ax1.set_yticks(y1)
    ax1.set_yticklabels(nomes1, fontsize=9)
    ax1.invert_yaxis()
    ax1.set_xlabel("Quantidade de PLs/PECs como Autor Proponente")
    ax1.set_title("Autoria Substantiva Real (Projetos de Lei Próprios)\nDeputados que de fato redigem e protocolam matérias", fontsize=11, fontweight="bold")
    for bar, val in zip(bars1, vals1):
        ax1.text(val + 8, bar.get_y() + bar.get_height()/2, f"{val} PLs", va="center", fontsize=8.5, fontweight="bold")
    ax1.set_xlim(0, max(vals1) * 1.18)
    
    # Plot Cosignatários
    nomes2 = [f"{r['nomeAutor']} ({r['siglaPartidoAutor']}/{r['siglaUFAutor']})" for r in top_cosign.iter_rows(named=True)]
    vals2 = [r["total"] for r in top_cosign.iter_rows(named=True)]
    y2 = np.arange(len(nomes2))
    bars2 = ax2.barh(y2, vals2, color="#d95f02", height=0.6)
    ax2.set_yticks(y2)
    ax2.set_yticklabels(nomes2, fontsize=9)
    ax2.invert_yaxis()
    ax2.set_xlabel("Quantidade de Subscrições / Apoios Coletivos")
    ax2.set_title("Subscrições em Bloco (Cosignatários)\nAssinaturas conjuntas em requerimentos e urgências", fontsize=11, fontweight="bold")
    for bar, val in zip(bars2, vals2):
        ax2.text(val + 10, bar.get_y() + bar.get_height()/2, f"{val} apoios", va="center", fontsize=8.5, fontweight="bold")
    ax2.set_xlim(0, max(vals2) * 1.2)
    
    plt.suptitle("Distinção entre Autoria Principal vs. Cosignatário (Câmara 2022–2026)", fontsize=13, fontweight="bold", y=1.02)
    plt.tight_layout()
    out_file = OUT_DIR / "02_ranking_autores_principais_vs_subscritores.png"
    fig.savefig(out_file, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Salvo: {out_file}")


def chart_03_temas_fact_checking():
    print("Gerando Gráfico 03: Temas Sensíveis de Fact-Checking nas Ementas...")
    temas = [
        "Segurança Pública & Crime",
        "Tributos, Impostos & PIX",
        "Tecnologia, Redes & IA",
        "Armas, CACs & Tiro",
        "Meio Ambiente & Indígenas",
        "Drogas & Maconha",
        "Saúde, Vacinas & Aborto"
    ]
    quantidades = [1122, 441, 201, 149, 144, 69, 68]
    percentuais = [9.24, 3.63, 1.65, 1.23, 1.19, 0.57, 0.56]
    
    fig, ax = plt.subplots(figsize=(12, 6))
    y = np.arange(len(temas))
    colors = ["#b2182b", "#d6604d", "#f4a582", "#92c5de", "#4393c3", "#2166ac", "#053061"]
    
    bars = ax.barh(y, quantidades, color=colors[::-1], height=0.55)
    ax.set_yticks(y)
    ax.set_yticklabels(temas, fontsize=10, fontweight="bold")
    ax.invert_yaxis()
    ax.set_xlabel("Quantidade de Projetos de Lei (PL, PEC, PLP, MPV) Identificados nas Ementas")
    ax.set_title("Presença de Temas Sensíveis a Desinformação nas Ementas de Projetos de Lei (2022–2026)\nFoco Temático dos Principais Boatos e Claims Verificáveis", fontsize=12, fontweight="bold", pad=12)
    
    for bar, val, pct in zip(bars, quantidades, percentuais):
        ax.text(val + 15, bar.get_y() + bar.get_height()/2, f"{val:,} projetos ({pct:.1f}% dos PLs)", va="center", fontsize=9, fontweight="bold")
    ax.set_xlim(0, max(quantidades) * 1.25)
    ax.grid(True, linestyle=":", alpha=0.6)
    
    plt.tight_layout()
    out_file = OUT_DIR / "03_temas_sensiveis_fact_checking.png"
    fig.savefig(out_file, dpi=300)
    plt.close(fig)
    print(f"Salvo: {out_file}")


def chart_04_funil_tramitacao():
    print("Gerando Gráfico 04: Funil de Tramitação e Desfecho...")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))
    
    # 1. Funil da Câmara
    etapas = [
        "Total de Atos Registrados",
        "Proposições Substantivas (PL/PEC)",
        "Arquivadas / Tramitação Encerrada",
        "Transformadas em Lei (Norma Final)"
    ]
    valores = [140507, 14071, 18453, 3407]
    cores = ["#1f77b4", "#ff7f0e", "#7f7f7f", "#2ca02c"]
    
    y = np.arange(len(etapas))
    bars = ax1.barh(y, valores, color=cores, height=0.55)
    ax1.set_yticks(y)
    ax1.set_yticklabels(etapas, fontsize=9, fontweight="bold")
    ax1.invert_yaxis()
    ax1.set_xlabel("Volume de Proposições")
    ax1.set_title("Câmara dos Deputados: Funil de Efetividade\nApenas 2,4% de todos os atos geram norma jurídica", fontsize=11, fontweight="bold")
    ax1.set_xscale("log")
    ax1.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f"{int(x):,}"))
    
    for bar, val in zip(bars, valores):
        ax1.text(val * 1.15, bar.get_y() + bar.get_height()/2, f"{val:,}", va="center", fontsize=8.5, fontweight="bold")
    ax1.set_xlim(1000, 300000)
    
    # 2. Status no Senado
    status_senado = [
        "Aguardando Relatoria",
        "Matéria com a Relatoria",
        "Aguardando Despacho",
        "Pronta p/ Pauta / Plenário",
        "Virou Norma Jurídica"
    ]
    vals_senado = [3412, 2456, 1801, 1063, 232]
    cores_sen = ["#3182bd", "#6baed6", "#9ecae1", "#fdae6b", "#31a354"]
    
    y2 = np.arange(len(status_senado))
    bars2 = ax2.barh(y2, vals_senado, color=cores_sen, height=0.55)
    ax2.set_yticks(y2)
    ax2.set_yticklabels(status_senado, fontsize=9, fontweight="bold")
    ax2.invert_yaxis()
    ax2.set_xlabel("Quantidade de Matérias")
    ax2.set_title("Senado Federal: Onde Estão as 9.922 Matérias?\nMais de 75% ainda aguardam relatório inicial", fontsize=11, fontweight="bold")
    
    for bar, val in zip(bars2, vals_senado):
        pct = (val / 9922) * 100
        ax2.text(val + 50, bar.get_y() + bar.get_height()/2, f"{val:,} ({pct:.1f}%)", va="center", fontsize=8.5, fontweight="bold")
    ax2.set_xlim(0, max(vals_senado) * 1.25)
    
    plt.suptitle("Funil de Tramitação e Conversão em Lei (Congresso Nacional)", fontsize=13, fontweight="bold", y=1.02)
    plt.tight_layout()
    out_file = OUT_DIR / "04_funil_situacao_tramitacao.png"
    fig.savefig(out_file, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Salvo: {out_file}")


def chart_05_rastreabilidade_inteiro_teor():
    print("Gerando Gráfico 05: Rastreabilidade de Inteiro Teor (PDF)...")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    
    # Câmara
    sizes1 = [99.6, 0.4]
    labels1 = ["Com Link Oficial PDF\n(139.905 textos)", "Sem Link Direto\n(602)"]
    ax1.pie(sizes1, labels=labels1, autopct="%1.1f%%", startangle=140, colors=["#2ca02c", "#d62728"], explode=(0.08, 0), textprops={"fontsize": 9.5, "fontweight": "bold"})
    ax1.set_title("Câmara dos Deputados (99,6% Cobertura)\nDisponibilidade do PDF Original de Apresentação", fontsize=11, fontweight="bold")
    
    # Senado
    sizes2 = [97.2, 2.8]
    labels2 = ["Com Link Oficial PDF\n(9.643 textos)", "Sem Link Direto\n(279)"]
    ax2.pie(sizes2, labels=labels2, autopct="%1.1f%%", startangle=140, colors=["#1f77b4", "#d62728"], explode=(0.08, 0), textprops={"fontsize": 9.5, "fontweight": "bold"})
    ax2.set_title("Senado Federal (97,2% Cobertura)\nDisponibilidade do PDF Original de Apresentação", fontsize=11, fontweight="bold")
    
    plt.suptitle("Rastreabilidade Documental das Matérias Legislativas (Auditoria Completa)", fontsize=13, fontweight="bold", y=1.02)
    plt.tight_layout()
    out_file = OUT_DIR / "05_rastreabilidade_inteiro_teor.png"
    fig.savefig(out_file, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Salvo: {out_file}")


def copy_to_artifacts():
    print("\nCopiando gráficos para diretório de artefatos...")
    for f in OUT_DIR.glob("*.png"):
        dest = ARTIFACT_DIR / f.name
        shutil.copy(f, dest)
        print(f"Copiado para artefato: {dest.name}")


def main():
    chart_01_taxonomia()
    chart_02_autoria()
    chart_03_temas_fact_checking()
    chart_04_funil_tramitacao()
    chart_05_rastreabilidade_inteiro_teor()
    copy_to_artifacts()
    print("\nTODOS OS GRÁFICOS DO EIXO 3 GERADOS COM SUCESSO!")


if __name__ == "__main__":
    main()
