from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "component-manifest.json").read_text(encoding="utf-8"))
if manifest.get("schema_version") != 1:
    raise SystemExit("unsupported component manifest schema")

for name in ("contracts", "ui", "ocr", "account"):
    expected = manifest[name]["commit"]
    line = subprocess.check_output(
        ["git", "ls-files", "--stage", f"components/{name}"], cwd=ROOT, text=True
    ).strip()
    actual = line.split()[1] if line else ""
    if actual != expected:
        raise SystemExit(f"{name} manifest/gitlink mismatch: {expected} != {actual}")
    if name != "contracts":
        lock = (ROOT / "components" / name / "contracts.lock").read_text(encoding="ascii").strip()
        if lock != manifest["contracts"]["commit"]:
            raise SystemExit(f"{name} uses contracts {lock}, Host uses {manifest['contracts']['commit']}")
print("component manifest and all contracts pins verified")
