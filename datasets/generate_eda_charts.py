import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
import re

# Set styling
plt.style.use('seaborn-v0_8-whitegrid')
plt.rcParams['font.sans-serif'] = 'DejaVu Sans'
plt.rcParams['font.size'] = 11
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['axes.labelsize'] = 12

output_dir = '/Users/aluno2/Documents/datasets/eda_charts'
os.makedirs(output_dir, exist_ok=True)

df = pd.read_csv('/Users/aluno2/Documents/datasets/FACTCKBR.tsv', sep='\t')

# Clean agency names for readability
agency_map = {
    'https:piaui.folha.uol.com.brlupa': 'Agência Lupa',
    'https:apublica.org': 'Agência Pública',
    'https:www.aosfatos.org': 'Aos Fatos'
}
df['agency_clean'] = df['Author'].map(agency_map).fillna(df['Author'])

# Parse dates
df['date'] = pd.to_datetime(df['datePublished'], format='mixed')

# Normalize labels
df['verdict_normalized'] = df['alternativeName'].str.strip().str.capitalize()
df['verdict_normalized'] = df['verdict_normalized'].fillna('Não informado')

# Compute text lengths
df['claim_words'] = df['claimReviewed'].fillna('').apply(lambda x: len(x.split()))
df['review_words'] = df['reviewBody'].fillna('').apply(lambda x: len(x.split()))
df['title_words'] = df['title'].fillna('').apply(lambda x: len(x.split()))

# -------------------------------------------------------------
# FIG 1: Distribuição por Agência (Volume Total vs Artigos Únicos)
# -------------------------------------------------------------
fig, ax = plt.subplots(figsize=(9, 5))
agency_stats = df.groupby('agency_clean').agg(
    total_claims=('URL', 'count'),
    unique_articles=('URL', 'nunique')
).reset_index()

x = np.arange(len(agency_stats))
width = 0.35

rects1 = ax.bar(x - width/2, agency_stats['total_claims'], width, label='Total de Declarações (Claims)', color='#1f77b4', edgecolor='none')
rects2 = ax.bar(x + width/2, agency_stats['unique_articles'], width, label='Artigos/URLs Únicas', color='#ff7f0e', edgecolor='none')

ax.set_ylabel('Quantidade de Registros')
ax.set_title('Volume de Checagens e URLs Únicas por Agência de Fact-Checking', fontweight='bold', pad=15)
ax.set_xticks(x)
ax.set_xticklabels(agency_stats['agency_clean'], fontweight='semibold')
ax.legend(frameon=True)

# Add values above bars
for rect in rects1:
    h = rect.get_height()
    ax.annotate(f'{h}', xy=(rect.get_x() + rect.get_width() / 2, h),
                xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontweight='bold')
for rect in rects2:
    h = rect.get_height()
    ax.annotate(f'{h}', xy=(rect.get_x() + rect.get_width() / 2, h),
                xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontweight='bold')

plt.tight_layout()
plt.savefig(os.path.join(output_dir, '01_volume_por_agencia.png'), dpi=300)
plt.close()

# -------------------------------------------------------------
# FIG 2: Distribuição Geral dos Vereditos Normalizados
# -------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 6))
verdict_counts = df['verdict_normalized'].value_counts()
top_verdicts = verdict_counts.head(7)
other_count = verdict_counts.iloc[7:].sum()
if other_count > 0:
    plot_series = pd.concat([top_verdicts, pd.Series({'Outros (Raros)': other_count})])
else:
    plot_series = top_verdicts

colors = ['#d62728', '#2ca02c', '#ff7f0e', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22']
bars = ax.barh(plot_series.index[::-1], plot_series.values[::-1], color=colors[:len(plot_series)][::-1])

for bar in bars:
    w = bar.get_width()
    pct = (w / len(df)) * 100
    ax.annotate(f'{w} ({pct:.1f}%)',
                xy=(w, bar.get_y() + bar.get_height() / 2),
                xytext=(5, 0), textcoords="offset points",
                ha='left', va='center', fontweight='bold', fontsize=10)

ax.set_xlabel('Número de Checagens')
ax.set_title('Distribuição de Vereditos no FACTCKBR (Desbalanceamento Severo de Classes)', fontweight='bold', pad=15)
ax.set_xlim(0, max(plot_series.values) * 1.18)
plt.tight_layout()
plt.savefig(os.path.join(output_dir, '02_distribuicao_vereditos.png'), dpi=300)
plt.close()

# -------------------------------------------------------------
# FIG 3: Vereditos por Agência
# -------------------------------------------------------------
fig, ax = plt.subplots(figsize=(11, 6))
# Filter top 5 categories, group rest in Outros
top5 = ['Falso', 'Verdadeiro', 'Exagerado', 'Distorcido', 'Sem contexto']
df['verdict_cat'] = df['verdict_normalized'].apply(lambda x: x if x in top5 else 'Outros')

cross_agency = pd.crosstab(df['agency_clean'], df['verdict_cat'], normalize='index') * 100
# Reorder columns
ordered_cols = ['Falso', 'Verdadeiro', 'Exagerado', 'Distorcido', 'Sem contexto', 'Outros']
cross_agency = cross_agency[ordered_cols]

cross_agency.plot(kind='bar', stacked=True, ax=ax, colormap='tab10', edgecolor='white', width=0.6)
ax.set_title('Proporção de Vereditos Emitidos por Cada Agência (%)', fontweight='bold', pad=15)
ax.set_ylabel('Porcentagem (%)')
ax.set_xlabel('')
ax.set_xticklabels(cross_agency.index, rotation=0, fontweight='semibold')
ax.legend(title='Veredito', bbox_to_anchor=(1.02, 1), loc='upper left', frameon=True)
ax.set_ylim(0, 100)

for p in ax.patches:
    h = p.get_height()
    if h > 5:
        ax.annotate(f'{h:.1f}%',
                    xy=(p.get_x() + p.get_width() / 2, p.get_y() + h / 2),
                    ha='center', va='center', fontsize=9, color='white', fontweight='bold')

plt.tight_layout()
plt.savefig(os.path.join(output_dir, '03_vereditos_por_agencia.png'), dpi=300)
plt.close()

# -------------------------------------------------------------
# FIG 4: Qualidade dos Dados - Anomalia de ratingValue por Agência
# -------------------------------------------------------------
fig, axes = plt.subplots(1, 3, figsize=(14, 5.2), sharey=True)

for i, (agency, group) in enumerate(df.groupby('agency_clean')):
    ax = axes[i]
    rv_counts = group['ratingValue'].fillna(-1).value_counts().sort_index()
    labels = [str(int(k)) if k >= 0 else 'NaN' for k in rv_counts.index]
    bars = ax.bar(labels, rv_counts.values, color='#3b528b' if 'Lupa' not in agency else '#b82e2e', edgecolor='none')
    ax.set_title(f'{agency}\n(bestRating={group["bestRating"].iloc[0]})', fontweight='bold', fontsize=12)
    ax.set_xlabel('ratingValue')
    if i == 0:
        ax.set_ylabel('Frequência')
    for bar in bars:
        h = bar.get_height()
        ax.annotate(f'{h}', xy=(bar.get_x() + bar.get_width()/2, h),
                    xytext=(0, 2), textcoords="offset points", ha='center', va='bottom', fontsize=9, fontweight='bold')

fig.suptitle('Anomalia Crítica de Qualidade: O Campo "ratingValue" por Agência\n(Note como a Lupa possui 100% fixo no valor 4.0)', fontweight='bold', y=0.96, fontsize=13)
plt.tight_layout(rect=[0, 0, 1, 0.88])
plt.savefig(os.path.join(output_dir, '04_anomalia_rating_value.png'), dpi=300)
plt.close()

# -------------------------------------------------------------
# FIG 5: Série Temporal (Evolução Mensal e Impacto Eleições 2018)
# -------------------------------------------------------------
df['year_month'] = df['date'].dt.to_period('M')
monthly_counts = df.groupby(['year_month', 'agency_clean']).size().unstack(fill_value=0)

fig, ax = plt.subplots(figsize=(12, 5.5))
monthly_counts.plot(kind='area', stacked=True, ax=ax, alpha=0.85, colormap='Set2')
ax.set_title('Evolução Temporal das Checagens de Fatos (2016 - 2019)', fontweight='bold', pad=15)
ax.set_xlabel('Mês de Publicação')
ax.set_ylabel('Checagens Publicadas por Mês')

# Highlight Election 2018
ax.axvline(pd.Period('2018-10', 'M'), color='red', linestyle='--', linewidth=2, label='Eleições 2018 (Outubro)')
ax.annotate('Pico Eleitoral 2018\n(Out/2018: 154 checagens)',
            xy=(pd.Period('2018-10', 'M'), 154),
            xytext=(pd.Period('2017-09', 'M'), 145),
            arrowprops=dict(facecolor='black', shrink=0.05, width=1.5, headwidth=8),
            fontweight='bold', bbox=dict(boxstyle='round,pad=0.4', facecolor='yellow', alpha=0.3))

ax.legend(title='Agência', loc='upper left', frameon=True)
plt.tight_layout()
plt.savefig(os.path.join(output_dir, '05_serie_temporal_eleicoes.png'), dpi=300)
plt.close()

# -------------------------------------------------------------
# FIG 6: Qualidade e Extensão dos Textos (Boxplots e Outliers)
# -------------------------------------------------------------
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

# Claim words by agency (clipped at 150 for clear visualization)
sns.boxplot(data=df, x='agency_clean', y='claim_words', ax=ax1, palette='Blues')
ax1.set_title('Extensão de "claimReviewed" por Agência (Palavras)', fontweight='bold')
ax1.set_xlabel('')
ax1.set_ylabel('Número de Palavras')
ax1.set_yscale('log')
ax1.set_title('Tamanho da Declaração ("claimReviewed") [Escala Log]\nOutliers extremos na Pública (>1.000 palavras)', fontweight='bold')

# Review body status
review_status = []
for idx, row in df.iterrows():
    val = row['reviewBody']
    if pd.isna(val):
        status = 'Ausente (NaN)'
    elif str(val).strip() == 'Empty':
        status = 'Literal "Empty"'
    else:
        status = 'Texto Presente'
    review_status.append(status)

df['review_status'] = review_status
cross_review = pd.crosstab(df['agency_clean'], df['review_status'])
cross_review.plot(kind='bar', stacked=True, ax=ax2, color=['#d62728', '#ff7f0e', '#2ca02c'], edgecolor='white', width=0.6)
ax2.set_title('Integridade de "reviewBody" por Agência\n(Lupa: 100% dos registros como "Empty")', fontweight='bold')
ax2.set_xlabel('')
ax2.set_ylabel('Total de Registros')
ax2.set_xticklabels(cross_review.index, rotation=0, fontweight='semibold')
ax2.legend(title='Status do Texto', frameon=True)

for p in ax2.patches:
    h = p.get_height()
    if h > 30:
        ax2.annotate(f'{int(h)}', xy=(p.get_x() + p.get_width()/2, p.get_y() + h/2),
                     ha='center', va='center', color='white', fontweight='bold')

plt.tight_layout()
plt.savefig(os.path.join(output_dir, '06_qualidade_textos_e_outliers.png'), dpi=300)
plt.close()

# -------------------------------------------------------------
# FIG 7: Principais Atores e Temas Políticos Checados
# -------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 6))
text_corpus = (df['claimReviewed'].fillna('') + ' ' + df['title'].fillna('')).str.lower()
entities = {
    'Jair Bolsonaro': r'\bbolsonaro\b',
    'Lula': r'\blula\b',
    'PT': r'\bpt\b',
    'Fernando Haddad': r'\bhaddad\b',
    'Michel Temer': r'\btemer\b',
    'Dilma Rousseff': r'\bdilma\b',
    'Sergio Moro': r'\bmoro\b',
    'Reforma Previdência': r'\bprevid[eê]ncia\b',
    'Ciro Gomes': r'\bciro\b',
    'Marina Silva': r'\bmarina\b',
    'STF / Supremo': r'\bstf\b',
    'SUS / Saúde': r'\bsus\b',
    'Fraude Eleitoral': r'\bfraude\b'
}

entity_counts = {k: text_corpus.str.contains(v, regex=True).sum() for k, v in entities.items()}
s_entities = pd.Series(entity_counts).sort_values(ascending=True)

bars = ax.barh(s_entities.index, s_entities.values, color='#17becf', edgecolor='none')
for bar in bars:
    w = bar.get_width()
    pct = (w / len(df)) * 100
    ax.annotate(f'{w} ({pct:.1f}%)',
                xy=(w, bar.get_y() + bar.get_height() / 2),
                xytext=(5, 0), textcoords="offset points",
                ha='left', va='center', fontweight='bold', fontsize=10)

ax.set_title('Frequência de Atores e Temas Políticos nas Declarações Analisadas', fontweight='bold', pad=15)
ax.set_xlabel('Quantidade de Menções')
ax.set_xlim(0, max(s_entities.values) * 1.18)
plt.tight_layout()
plt.savefig(os.path.join(output_dir, '07_atores_e_temas_politicos.png'), dpi=300)
plt.close()

print("ALL 7 CHARTS GENERATED SUCCESSFULLY IN:", output_dir)
