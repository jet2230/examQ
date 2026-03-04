import re, sys

text = sys.stdin.read()
print("--- RAW TEXT SAMPLE ---")
print(text[:500])
print("--- MATCHES ---")

# 1. Main
main_matches = re.findall(r'^\s*(?:Question\s+)?(\d+)(?:\.|\s{2,})', text, re.MULTILINE | re.IGNORECASE)
print(f"Main: {main_matches}")

# 2. Sub
sub_matches = re.findall(r'^\s*\(([a-z]+)\)(?:\s*\(([ivx]+)\))?', text, re.MULTILINE | re.IGNORECASE)
print(f"Sub: {sub_matches}")

# 3. Combined
comb_matches = re.findall(r'^\s*(?:Question\s+)?(\d+)\s*\(([a-z]+)\)(?:\s*\(([ivx]+)\))?', text, re.MULTILINE | re.IGNORECASE)
print(f"Combined: {comb_matches}")
