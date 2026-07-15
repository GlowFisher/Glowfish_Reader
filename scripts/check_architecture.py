from pathlib import Path
import re

PRIVATE = re.compile(r"(?:from|import)\s+(?:glowfish_ocr\.legacy|licensing|glowfish_account_server)\b")
for path in Path("src/glowfish_host").rglob("*.py"):
    if PRIVATE.search(path.read_text(encoding="utf-8")):
        raise SystemExit(f"Host private component import forbidden: {path}")
print("Host public dependency boundary verified")
