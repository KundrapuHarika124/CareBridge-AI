"""Checks that en.json and te.json have identical keys, identical {{placeholders}}, and that
every static translation key used in frontend/src exists. Exit code 1 on any problem."""
import json, re, sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent / "frontend" / "src"

def flat(node, prefix=""):
    out = {}
    for k, v in node.items():
        if isinstance(v, dict):
            out.update(flat(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out

en = flat(json.loads((root / "locales/en.json").read_text(encoding="utf-8")))
te = flat(json.loads((root / "locales/te.json").read_text(encoding="utf-8")))
problems = []
for k in sorted(set(en) ^ set(te)):
    problems.append(f"key in only one language: {k}")
ph = lambda s: sorted(re.findall(r"\{\{(\w+)\}\}", s))
for k in sorted(set(en) & set(te)):
    if ph(en[k]) != ph(te[k]):
        problems.append(f"placeholder mismatch: {k}")
    if not en[k].strip() or not te[k].strip():
        problems.append(f"empty text: {k}")
used, prefixes = set(), set()
for path in root.rglob("*.ts*"):
    text = path.read_text(encoding="utf-8")
    for m in re.finditer(r"""\bt\(\s*["'`]([A-Za-z0-9_.]+)(\$\{)?""", text):
        (prefixes if m.group(2) else used).add(m.group(1))
    used.update(re.findall(r'key: "([A-Za-z.]+)"', text))
for k in sorted(used):
    if k not in en and "." in k:
        problems.append(f"used but not defined: {k}")
for p in sorted(prefixes):
    if not any(k.startswith(p) for k in en):
        problems.append(f"dynamic prefix has no keys: {p}")
unused = [k for k in en if k not in used and not any(k.startswith(p) for p in prefixes)]
print(f"keys: {len(en)} en / {len(te)} te; static keys used: {len(used)}; dynamic prefixes: {len(prefixes)}; defined but not referenced statically: {len(unused)}")
for u in unused:
    print("  note, unreferenced:", u)
for p in problems:
    print("PROBLEM:", p)
sys.exit(1 if problems else 0)
