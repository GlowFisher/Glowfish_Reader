from __future__ import annotations

import json
from pathlib import Path

from workspace_paths import component_root, workspace_root

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "component-manifest.json").read_text(encoding="utf-8"))
if manifest.get("schema_version") != 1:
    raise SystemExit("unsupported component manifest schema")

# 单仓库 monorepo：组件均为同仓目录，仅校验目录存在，不再做跨仓库 commit 锁定。
for name in ("contracts", "ui", "ocr"):
    repo = component_root(name)
    if not repo.is_dir():
        raise SystemExit(f"component directory missing: {name}")

print(f"component directories verified from {workspace_root()}")
