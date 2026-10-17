"""单仓库 monorepo 下，contracts 为同仓目录，无需跨仓库 commit 锁定。

保留本脚本仅为向后兼容占位：校验 contracts 源码目录存在即可。
"""
from pathlib import Path

contracts_root = Path(__file__).resolve().parents[2] / "contracts"
if not (contracts_root / "src" / "glowfish_contracts").is_dir():
    raise SystemExit("contracts component missing")

print("contracts component present (monorepo)")
