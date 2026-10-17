"""Generate the unsigned, hash-pinned GPU runtime manifest for release signing."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_runtime_archive(path: Path) -> None:
    """Require the optional-runtime archive to contain only the Worker.

    OCR models remain in the signed desktop application.  Accepting arbitrary
    archive members here would permit accidental model duplication or a path
    traversal payload before the Host's installer receives the release.
    """
    if path.suffix.lower() != ".zip":
        raise ValueError("GPU runtime artifact must be a .zip archive")
    with zipfile.ZipFile(path) as bundle:
        names = [item.filename.replace("\\", "/") for item in bundle.infolist() if not item.is_dir()]
    if any(name.startswith("/") or ".." in Path(name).parts for name in names):
        raise ValueError("GPU runtime archive contains an unsafe path")
    if names != ["glowfish_gpu_worker.exe"]:
        raise ValueError("GPU runtime archive must contain exactly glowfish_gpu_worker.exe and no OCR models")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--artifact-url", required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--models-lock", type=Path, required=True)
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--min-app-version", required=True)
    parser.add_argument("--max-app-version", required=True)
    parser.add_argument("--min-driver-version", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not args.artifact_url.startswith("https://"):
        raise SystemExit("artifact URL must use HTTPS")
    artifact = args.artifact.resolve()
    if not artifact.is_file():
        raise SystemExit(f"GPU runtime artifact does not exist: {artifact}")
    if not args.models_lock.is_file():
        raise SystemExit(f"models lock does not exist: {args.models_lock}")
    try:
        validate_runtime_archive(artifact)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"invalid GPU runtime archive: {exc}") from exc
    payload = {
        "schema_version": 1, "runtime_version": args.runtime_version,
        "protocol_version": 2, "min_app_version": args.min_app_version, "max_app_version": args.max_app_version,
        "artifact": {"url": args.artifact_url, "sha256": sha256(artifact),
                     "size": artifact.stat().st_size, "authenticode_subject": args.publisher},
        "device": {"min_compute_capability": "7.5", "min_vram_mb": 6144,
                   "min_driver_version": args.min_driver_version},
        "supported_engines": ["ppocrv6_onnx", "ppocrv6_onnx_high"],
        "models_lock_sha256": sha256(args.models_lock.resolve()),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
