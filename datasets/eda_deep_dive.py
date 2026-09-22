import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os

# Set style
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams['font.sans-serif'] = 'DejaVu Sans'
plt.rcParams['font.size'] = 11

df = pd.read_csv('FACTCKBR.tsv', sep='\t')

print("--- DETAILED AUTHOR & RATING SYSTEM ANALYSIS ---")
for author, group in df.groupby('Author'):
    print(f"\nAuthor: {author}")
    print(f"Total claims: {len(group)}")
    print(f"Unique URLs: {group['URL'].nunique()}")
    print(f"bestRating values: {group['bestRating'].unique()}")
    print("ratingValue vs alternativeName:")
    print(pd.crosstab(group['ratingValue'], group['alternativeName'].fillna('MISSING'), dropna=False))

print("\n--- MULTI-CLAIM URLS ---")
url_counts = df['URL'].value_counts()
print(f"URLs with >1 claim: {(url_counts > 1).sum()}")
print(f"Max claims per URL: {url_counts.max()}")
top_multi = url_counts[url_counts > 1].head(3)
for url, count in top_multi.items():
    print(f"\nURL ({count} claims): {url}")
    sample_claims = df[df['URL'] == url]['claimReviewed'].tolist()
    for i, c in enumerate(sample_claims[:3]):
        print(f"  Claim {i+1}: {str(c)[:100]}...")

print("\n--- MISSING VALUE ROWS ---")
missing_rows = df[df.isnull().any(axis=1)]
print(f"Total rows with at least one missing field: {len(missing_rows)}")
print(missing_rows[['Author', 'claimReviewed', 'reviewBody', 'ratingValue', 'alternativeName']].to_string())

# Label normalization
df['label_normalized'] = df['alternativeName'].str.strip().str.capitalize()
print("\n--- NORMALIZED LABELS ---")
print(df['label_normalized'].value_counts(dropna=False))

# Date parsing
df['date'] = pd.to_datetime(df['datePublished'], errors='coerce', utc=True)
print("\n--- DATES ---")
print("Null dates:", df['date'].isnull().sum())
print("Yearly distribution:")
print(df['date'].dt.year.value_counts().sort_index())

# Text length stats
df['claim_len_chars'] = df['claimReviewed'].fillna('').apply(len)
df['claim_len_words'] = df['claimReviewed'].fillna('').apply(lambda x: len(x.split()))
df['review_len_words'] = df['reviewBody'].fillna('').apply(lambda x: len(x.split()))
df['title_len_words'] = df['title'].fillna('').apply(lambda x: len(x.split()))

print("\n--- TEXT STATS SUMMARY ---")
print(df[['claim_len_chars', 'claim_len_words', 'review_len_words', 'title_len_words']].describe())

# Save enriched dataset copy or stats for reference
os.makedirs('eda_output', exist_ok=True)
