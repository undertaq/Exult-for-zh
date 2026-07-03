"""Compare expected voice file names (from mapping) vs actual files in zh/ directory."""
import csv, sys, os, re
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

# Read the offset mapping
mapping = []
with open('tools/voice_acting/offset_mapping.csv', 'r', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        mapping.append(row)

# Generate expected filenames for ZH (from mapping's zh_func_id + zh_offset_key + zh_segment)
expected_zh = set()
for e in mapping:
    fid = e['zh_func_id'].replace('0x', '').lower().zfill(4)
    key = e['zh_offset_key']
    seg = e['zh_segment']
    expected_zh.add(f"{fid}_{key}_{seg}.ogg")

print(f"Expected ZH files from mapping: {len(expected_zh)}")

# Read actual files from zh/ directory
zh_dir = r'../Ultima_7/patch/voice_acting/zh'
actual_files = set()
if os.path.isdir(zh_dir):
    for fname in os.listdir(zh_dir):
        if fname.endswith('.ogg') or fname.endswith('.wav'):
            actual_files.add(fname)

print(f"Actual files in zh/: {len(actual_files)}")

# Find files that are expected but missing
missing = expected_zh - actual_files
extra = actual_files - expected_zh

print(f"Expected-but-missing: {len(missing)}")
print(f"Extra (not in mapping): {len(extra)}")

# Check for naming convention differences
print("\n=== SAMPLE EXPECTED FILENAMES (first 20) ===")
for name in sorted(expected_zh)[:20]:
    print(f"  {name}")

print("\n=== SAMPLE ACTUAL FILENAMES (first 20) ===")
for name in sorted(actual_files)[:20]:
    print(f"  {name}")

# Check if actual files use EN naming instead of ZH naming
print("\n=== Checking for EN-key-named files in zh/ ===")
en_named = [f for f in actual_files if any(e['en_offset_key'] in f for e in mapping[:100])]
if en_named:
    print(f"  Found {len(en_named)} files that might use EN naming:")
    for f in en_named[:10]:
        print(f"    {f}")
else:
    print("  None found (good)")

# Check for 0000_ prefix (func_id fallback)
zeros = [f for f in actual_files if f.startswith('0000_')]
print(f"\nFiles with 0000_ prefix (func_id fallback): {len(zeros)}")
if zeros:
    for f in zeros[:10]:
        print(f"  {f}")

# Check mapping for 0000_ expected entries
zeros_expected = [f for f in expected_zh if f.startswith('0000_')]
print(f"Expected files with 0000_ prefix: {len(zeros_expected)}")
