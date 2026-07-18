# -*- coding: utf-8 -*-
from pathlib import Path


SCRIPT = Path(__file__).with_name("release.ps1")


def test_release_runs_all_frozen_gates_before_inno_setup():
    text = SCRIPT.read_text(encoding="utf-8")

    helper = text.index("function Invoke-FrozenGate")
    capabilities = text.index('Invoke-FrozenGate "capabilities" "--selftest-capabilities"')
    service = text.index('Invoke-FrozenGate "service selftest" "--selftest"')
    deps = text.index('Invoke-FrozenGate "OCR dependency metadata" "--selftest-ocr-deps"')
    ocr = text.index('Invoke-FrozenGate "offline OCR selftest" "--selftest-ocr"')
    resident = text.index(
        'Invoke-FrozenGate "resident OCR Unicode path selftest" "--selftest-ocr-resident"'
    )
    iscc = text.index("$isccCandidates")

    assert helper < capabilities < service < deps < ocr < resident < iscc
    assert "$psi = New-Object System.Diagnostics.ProcessStartInfo" in text
    assert "$p = [System.Diagnostics.Process]::Start($psi)" in text
    assert "$p.WaitForExit()" in text


def test_release_runs_packaging_preflight_before_optional_build():
    text = SCRIPT.read_text(encoding="utf-8")

    preflight = text.index('& $py (Join-Path $here "packaging_preflight.py")')
    build = text.index('& $py -m PyInstaller')

    assert preflight < build
    assert '& $py -m PyInstaller --clean --noconfirm' in text


def test_release_accepts_explicit_build_python():
    text = SCRIPT.read_text(encoding="utf-8")

    assert '[string]$Python = ""' in text
    assert "$py = $Python" in text
    assert "$py = $env:GLOWFISH_BUILD_PYTHON" in text
    assert "pass -Python or set GLOWFISH_BUILD_PYTHON" in text


def test_release_keeps_artifacts_outside_source_tree_by_default():
    text = SCRIPT.read_text(encoding="utf-8")

    assert '[string]$OutputDir = ""' in text
    assert 'Join-Path $BuildRoot "artifacts"' in text
    assert '"/DSourceDir=$distDir"' in text
    assert '"/DOutputDir=$OutputDir"' in text
    assert '$built = Join-Path $OutputDir $setupFileName' in text
    assert '$manifestPath = Join-Path $OutputDir "update.json"' in text
