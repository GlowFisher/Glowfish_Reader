import os
from pathlib import Path
import subprocess

expected = Path("contracts.lock").read_text(encoding="ascii").strip()
if len(expected) != 40 or any(char not in "0123456789abcdef" for char in expected):
    raise SystemExit(f"invalid contracts lock: {expected}")

contracts_root = os.environ.get("GLOWFISH_CONTRACTS_ROOT")
if contracts_root:
    actual = subprocess.check_output(
        ["git", "-C", contracts_root, "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != expected:
        raise SystemExit(f"contracts worktree mismatch: expected {expected}, got {actual}")
print(f"contracts compatibility pinned at {expected}")
