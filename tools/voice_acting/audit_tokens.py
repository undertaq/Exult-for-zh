"""Audit all angle-bracket tokens in the bilingual mapping pipeline."""
import json, csv, re
from collections import Counter

def extract_tokens(text):
    return re.findall(r'<[^>]+>', text)

# Check v2.json
with open(r"D:\Project\Exult-for-zh\tools\voice_acting\bilingual_mapping_review_v2.json", "r", encoding="utf-8") as f:
    data = json.load(f)

tokens_en = Counter()
tokens_zh = Counter()
for e in data:
    for t in extract_tokens(e.get("en_text", "")):
        tokens_en[t.lower()] += 1
    for t in extract_tokens(e.get("zh_text", "")):
        tokens_zh[t] += 1

print("=== EN tokens ===")
for t, n in tokens_en.most_common():
    print(f"  {t}: {n}")

print("\n=== ZH tokens ===")
for t, n in tokens_zh.most_common():
    print(f"  {t}: {n}")

# Also check source CSVs
print("\n=== bilingual_mapping.csv ZH tokens ===")
tokens_csv = Counter()
with open(r"D:\Project\Exult-for-zh\tools\voice_acting\bilingual_mapping.csv", "r", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        for t in extract_tokens(row.get("zh_text", "")):
            tokens_csv[t] += 1
for t, n in tokens_csv.most_common():
    print(f"  {t}: {n}")

print("\n=== bilingual_mapping_static.csv ZH tokens ===")
tokens_static = Counter()
with open(r"D:\Project\Exult-for-zh\tools\voice_acting\bilingual_mapping_static.csv", "r", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        for t in extract_tokens(row.get("zh_text", "")):
            tokens_static[t] += 1
for t, n in tokens_static.most_common():
    print(f"  {t}: {n}")

# Show sample entries for each token type in v2.json
print("\n=== Sample entries per token type ===")
for token in sorted(tokens_zh.keys()):
    for e in data:
        if token in e.get("zh_text", ""):
            en = e.get("en_text", "")
            zh = e.get("zh_text", "")
            print(f"\n{token}:")
            print(f"  EN: {en[:100]}")
            print(f"  ZH: {zh[:100]}")
            break
