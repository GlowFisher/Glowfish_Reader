from pathlib import Path


FORBIDDEN = ("glowfish_host", "glowfish_account", "proofread", "license_server")
ROOT = Path(__file__).resolve().parents[1] / "src" / "glowfish_ocr"

violations = []
for path in ROOT.rglob("*.py"):
    text = path.read_text(encoding="utf-8")
    for name in FORBIDDEN:
        if f"import {name}" in text or f"from {name}" in text:
            violations.append(f"{path.relative_to(ROOT)} imports {name}")
if violations:
    raise SystemExit("\n".join(violations))
print("OCR public package dependency boundary verified")
