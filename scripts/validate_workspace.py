from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "workspace-manifest.json").read_text(encoding="utf-8"))
COMPONENTS = ("host", "ui", "ocr", "contracts")


if MANIFEST.get("schema_version") != 2:
    raise SystemExit("unsupported workspace manifest schema")

# 单仓库 monorepo：各组件均为同仓目录，仅校验目录存在。
for name in COMPONENTS:
    path = ROOT / name
    if not path.is_dir():
        raise SystemExit(f"component directory missing: {name}")

print("workspace components verified (monorepo)")
