from pathlib import Path
import subprocess

expected = Path("contracts.lock").read_text(encoding="ascii").strip()
line = subprocess.check_output(["git", "ls-files", "--stage", "components/contracts"], text=True).strip()
actual = line.split()[1] if line else ""
if len(expected) != 40 or actual != expected:
    raise SystemExit(f"contracts gitlink mismatch: expected {expected}, got {actual}")
print(f"contracts pinned at {actual}")
