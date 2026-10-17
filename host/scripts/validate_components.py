from __future__ import annotations

import json
import subprocess
from pathlib import Path

from workspace_paths import component_root, workspace_root

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "component-manifest.json").read_text(encoding="utf-8"))
if manifest.get("schema_version") != 1:
    raise SystemExit("unsupported component manifest schema")

for name in ("contracts", "ui", "ocr", "account"):
    expected = manifest[name]["commit"]
    repo = component_root(name)
    actual = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != expected:
        raise SystemExit(f"{name} manifest/worktree mismatch: {expected} != {actual}")
    if name != "contracts":
        lock = (repo / "contracts.lock").read_text(encoding="ascii").strip()
        if lock != manifest["contracts"]["commit"]:
            raise SystemExit(f"{name} uses contracts {lock}, Host uses {manifest['contracts']['commit']}")
print(f"component manifest and all contracts pins verified from {workspace_root()}")
