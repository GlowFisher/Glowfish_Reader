# -*- coding: utf-8 -*-
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import packaging_payload_audit


HERE = Path(__file__).resolve().parent
PRODUCT = "Glowfish Reader V1.0.1"


def test_release_identity_is_exact_and_consistent():
    installer = (HERE / "installer.iss").read_text(encoding="utf-8")
    spec = (HERE / "glowfish_reader.spec").read_text(encoding="utf-8")
    release = (HERE / "release.ps1").read_text(encoding="utf-8")
    version_info = (HERE / "version_info.txt").read_text(encoding="utf-8")

    assert '__version__ = "1.0.1"' in (HERE / "_version.py").read_text(encoding="utf-8")
    assert '#define AppDisplayName AppBaseName + " V" + AppVersion' in installer
    assert 'AppName={#AppDisplayName}' in installer
    assert 'AppVerName={#AppDisplayName}' in installer
    assert 'DefaultDirName={localappdata}\\Programs\\{#AppDisplayName}' in installer
    assert 'OutputBase AppDisplayName + " Setup"' in installer
    assert 'name=PRODUCT_DISPLAY_NAME' in spec
    assert 'version=os.path.join(HERE, "version_info.txt")' in spec
    assert '$setupBase = "$productName Setup"' in release
    assert '$psi.WorkingDirectory = $distDir' in release
    assert '$env:SHUPAI_DATA_DIR = $gateDataRoot' in release
    assert 'paddlex_cache.configure_paddlex_cache(appconfig.data_root())' in (
        HERE / "recognize_ppocrv6_onnx.py"
    ).read_text(encoding="utf-8")
    assert f"StringStruct('ProductName', '{PRODUCT}')" in version_info
    assert f"StringStruct('OriginalFilename', '{PRODUCT}.exe')" in version_info

    assert "filevers=(1, 0, 1, 0)" in version_info
    assert "prodvers=(1, 0, 1, 0)" in version_info


def test_release_runs_latest_fix_and_payload_security_gates():
    release = (HERE / "release.ps1").read_text(encoding="utf-8")
    fix_gate = release.index('Invoke-FrozenGate "image export + runtime logging fixes"')
    payload_gate = release.index('"packaging_payload_audit.py"')
    iscc = release.index("$isccCandidates")
    assert fix_gate < payload_gate < iscc


def test_release_fix_selftest_passes_from_source():
    env = os.environ.copy()
    result = subprocess.run(
        [sys.executable, "desktop_app.py", "--selftest-release-fixes"],
        cwd=HERE,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SELFTEST RELEASE FIXES OK" in result.stdout


def _clean_payload(tmp_path, monkeypatch):
    product = PRODUCT
    internal = tmp_path / "_internal"
    ui_dist = internal / "ui_dist"
    ui_dist.mkdir(parents=True)
    (internal / "models" / "ppocrv6_onnx").mkdir(parents=True)
    index = ui_dist / "index.html"
    index.write_text("ok", encoding="utf-8")
    (ui_dist / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "files": [{"path": "index.html", "bytes": index.stat().st_size, "sha256": hashlib.sha256(index.read_bytes()).hexdigest()}],
    }), encoding="utf-8")
    (internal / "component-manifest.json").write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    (internal / "sku.txt").write_text("single", encoding="utf-8")
    (tmp_path / f"{product}.exe").write_bytes(b"MZ")
    fake_pyz = SimpleNamespace(toc={"desktop_app": None, "export_api": None})
    fake_archive = SimpleNamespace(open_embedded_archive=lambda _name: fake_pyz)
    monkeypatch.setattr(packaging_payload_audit, "CArchiveReader", lambda _path: fake_archive)
    return product


def test_payload_audit_accepts_clean_client(monkeypatch, tmp_path):
    product = _clean_payload(tmp_path, monkeypatch)
    assert packaging_payload_audit.audit_payload(tmp_path, product) == []


def test_payload_audit_rejects_private_key(monkeypatch, tmp_path):
    product = _clean_payload(tmp_path, monkeypatch)
    (tmp_path / "server_private.key").write_text("secret", encoding="utf-8")
    errors = packaging_payload_audit.audit_payload(tmp_path, product)
    assert any("sensitive file" in error for error in errors)


def test_payload_audit_allows_public_ca_certificate(monkeypatch, tmp_path):
    product = _clean_payload(tmp_path, monkeypatch)
    (tmp_path / "_internal" / "cacert.pem").write_text("-----BEGIN CERTIFICATE-----\npublic\n", encoding="utf-8")
    assert packaging_payload_audit.audit_payload(tmp_path, product) == []


def test_payload_audit_rejects_private_key_pem(monkeypatch, tmp_path):
    product = _clean_payload(tmp_path, monkeypatch)
    (tmp_path / "_internal" / "server.pem").write_text("-----BEGIN PRIVATE KEY-----\nsecret\n", encoding="utf-8")
    errors = packaging_payload_audit.audit_payload(tmp_path, product)
    assert any("private key material" in error for error in errors)

def test_payload_audit_rejects_unexpected_empty_top_level_directory(monkeypatch, tmp_path):
    product = _clean_payload(tmp_path, monkeypatch)
    (tmp_path / "proofread" / "_work").mkdir(parents=True)
    errors = packaging_payload_audit.audit_payload(tmp_path, product)
    assert any("unexpected top-level payload entry: proofread" in error for error in errors)
