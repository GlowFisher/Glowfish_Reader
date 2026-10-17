# -*- coding: utf-8 -*-
"""Fail a release when the frozen client payload contains development or secret material."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


FORBIDDEN_PARTS = {".git", ".planning", "license_server", "_keys"}
FORBIDDEN_SUFFIXES = {".key", ".pfx", ".p12", ".db", ".sqlite", ".sqlite3"}
FORBIDDEN_NAMES = {".env", "license.json", "last_error.log", "users.db", "account.db"}
CLIENT_SOURCE_PACKAGES = {"pipeline"}
FORBIDDEN_ARCHIVE_PREFIXES = ("license_server", "serverapp")


def audit_payload(dist_dir: Path, product_name: str) -> list[str]:
    dist_dir = dist_dir.resolve()
    errors: list[str] = []
    exe = dist_dir / f"{product_name}.exe"
    if not exe.is_file():
        errors.append(f"expected executable missing: {exe.name}")

    allowed_top_level = {f"{product_name}.exe".casefold(), "_internal"}
    for path in dist_dir.iterdir():
        if path.name.casefold() not in allowed_top_level:
            errors.append(f"unexpected top-level payload entry: {path.name}")

    files = [path for path in dist_dir.rglob("*") if path.is_file()]
    for path in files:
        rel = path.relative_to(dist_dir)
        parts = tuple(part.casefold() for part in rel.parts)
        name = path.name.casefold()
        suffix = path.suffix.casefold()
        if FORBIDDEN_PARTS.intersection(parts):
            errors.append(f"forbidden path component: {rel}")
        if name in FORBIDDEN_NAMES or suffix in FORBIDDEN_SUFFIXES or name.startswith(".env."):
            errors.append(f"forbidden sensitive file: {rel}")
        if suffix == ".pem" and b"PRIVATE KEY" in path.read_bytes():
            errors.append(f"private key material in PEM file: {rel}")
        if suffix in {".py", ".pyc"}:
            first_party_raw = (
                len(parts) <= 2
                or (len(parts) > 1 and parts[1] in CLIENT_SOURCE_PACKAGES)
            )
            if first_party_raw:
                errors.append(f"raw first-party Python source/bytecode: {rel}")

    required = (
        dist_dir / "_internal" / "sku.txt",
        dist_dir / "_internal" / "ui_dist" / "index.html",
        dist_dir / "_internal" / "ui_dist" / "manifest.json",
        dist_dir / "_internal" / "component-manifest.json",
        dist_dir / "_internal" / "models" / "ppocrv6_onnx",
    )
    for path in required:
        if not path.exists():
            errors.append(f"required runtime asset missing: {path.relative_to(dist_dir)}")
    ui_manifest_path = dist_dir / "_internal" / "ui_dist" / "manifest.json"
    if ui_manifest_path.is_file():
        try:
            ui_manifest = json.loads(ui_manifest_path.read_text(encoding="utf-8"))
            for item in ui_manifest.get("files", []):
                asset = ui_manifest_path.parent / item["path"]
                if not asset.is_file() or asset.stat().st_size != item["bytes"] or hashlib.sha256(asset.read_bytes()).hexdigest() != item["sha256"]:
                    errors.append(f"UI manifest hash mismatch: {item.get('path')}")
        except Exception as exc:
            errors.append(f"invalid UI payload manifest: {exc}")
    component_manifest = dist_dir / "_internal" / "component-manifest.json"
    if component_manifest.is_file():
        try:
            if json.loads(component_manifest.read_text(encoding="utf-8")).get("schema_version") != 1:
                errors.append("unsupported embedded component manifest schema")
        except Exception as exc:
            errors.append(f"invalid embedded component manifest: {exc}")

    sku = dist_dir / "_internal" / "sku.txt"
    if sku.is_file() and sku.read_text(encoding="utf-8").strip().casefold() != "single":
        errors.append("sku.txt is not locked to single")

    if exe.is_file():
        try:
            archive = CArchiveReader(str(exe))
            pyz = archive.open_embedded_archive("PYZ.pyz")
            for module in pyz.toc:
                lowered = module.casefold()
                if lowered == "serverapp" or lowered.startswith("license_server"):
                    errors.append(f"server/admin module embedded in client archive: {module}")
        except Exception as exc:
            errors.append(f"unable to inspect PyInstaller archive: {exc}")

    print(f"[payload-audit] files={len(files)} product={product_name}")
    if errors:
        for error in errors:
            print(f"[payload-audit] FAIL: {error}")
    else:
        print("[payload-audit] OK: no private keys, databases, server modules, or raw first-party Python files")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: packaging_payload_audit.py <dist_dir> <product_name>")
        return 2
    return 1 if audit_payload(Path(argv[1]), argv[2]) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
