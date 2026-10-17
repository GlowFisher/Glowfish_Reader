"""Exercise a local unsigned GPU-runtime candidate through the installer lifecycle.

This is intentionally not a release installer: signature success is simulated
only when the caller explicitly supplies ``--allow-unsigned-local-candidate``.
The extracted Worker self-test remains real.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host-src", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--models-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-unsigned-local-candidate", action="store_true")
    args = parser.parse_args(argv)
    if not args.allow_unsigned_local_candidate:
        raise SystemExit("refusing unsigned candidate; pass --allow-unsigned-local-candidate")
    if not args.archive.is_file() or not args.manifest.is_file() or not args.models_root.is_dir():
        raise SystemExit("archive, manifest, or models root is missing")
    sys.path.insert(0, str(args.host_src.resolve()))
    from glowfish_host.acceleration import GpuRuntimeInstaller, GpuRuntimeManager

    manifest_bytes = args.manifest.read_bytes()

    def download(url: str, destination: Path) -> None:
        if url.endswith("manifest.json"):
            destination.write_bytes(manifest_bytes)
        else:
            shutil.copyfile(args.archive, destination)

    def self_test(runtime: Path) -> bool:
        worker = runtime / "glowfish_gpu_worker.exe"
        env = dict(os.environ)
        env["SHUPAI_DATA_DIR"] = str(args.runtime_root / "selftest-cache")
        completed = subprocess.run(
            [str(worker), "--selftest", "--models-root", str(args.models_root)],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        # The frozen Worker is a windowed executable: a successful strict
        # self-test may not expose stdout through this parent process.  Its
        # process exit is authoritative because the Worker itself fails closed
        # before OCR if CUDA Session creation or the model smoke test fails.
        return completed.returncode == 0

    manager = GpuRuntimeManager(args.runtime_root, app_version="1.0.3")
    installer = GpuRuntimeInstaller(
        manager,
        manifest_url="https://local.invalid/manifest.json",
        download=download,
        verify_signature=lambda _path, _subject: True,
        self_test=self_test,
    )
    installer._install()
    ready = manager.status(preference="auto")
    manager.mark_active()
    active = manager.status(preference="auto")
    manager.mark_degraded("gpu_oom")
    fallback = manager.status(preference="auto")
    manager.uninstall()
    removed = manager.status(preference="cpu")
    report = {
        "unsigned_signature_simulated": True,
        "installer_ready": ready,
        "active": active,
        "oom_fallback": fallback,
        "uninstall": removed,
        "ok": (
            ready["state"] == "ready"
            and active["active_provider"] == "cuda"
            and fallback["active_provider"] == "cpu"
            and fallback["reason_code"] == "gpu_oom"
            and removed["state"] == "not_installed"
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
