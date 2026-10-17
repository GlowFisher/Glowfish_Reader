"""Verify a pinned GPU Worker build environment and emit its provenance."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path


def _version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError(f"required package is missing: {name}") from exc


def verify(lock: dict, *, require_release_qualified: bool = False) -> dict:
    if lock.get("schema_version") != 1:
        raise RuntimeError("unsupported GPU build lock schema")
    if require_release_qualified and not lock.get("release_qualified"):
        raise RuntimeError("build lock is candidate-only, not release-qualified")
    expected_python = str(lock.get("python") or "")
    actual_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    if actual_python != expected_python:
        raise RuntimeError(f"Python mismatch: expected {expected_python}, got {actual_python}")
    packages = lock.get("packages")
    if not isinstance(packages, dict) or not packages:
        raise RuntimeError("GPU build lock has no packages")
    actual_packages = {name: _version(name) for name in packages}
    mismatches = {
        name: {"expected": expected, "actual": actual_packages[name]}
        for name, expected in packages.items()
        if str(expected) != actual_packages[name]
    }
    if mismatches:
        raise RuntimeError(f"GPU package lock mismatch: {json.dumps(mismatches, sort_keys=True)}")
    import onnxruntime

    provider = str(lock.get("required_provider") or "CUDAExecutionProvider")
    providers = list(onnxruntime.get_available_providers())
    if provider not in providers:
        raise RuntimeError(f"required ONNX Runtime provider is unavailable: {provider}; got {providers}")
    return {
        "schema_version": 1,
        "label": lock.get("label"),
        "release_qualified": bool(lock.get("release_qualified")),
        "python": actual_python,
        "packages": actual_packages,
        "providers": providers,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--require-release-qualified", action="store_true")
    args = parser.parse_args(argv)
    try:
        lock = json.loads(args.lock.read_text(encoding="utf-8"))
        report = verify(lock, require_release_qualified=args.require_release_qualified)
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"GPU build environment rejected: {exc}") from exc
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
