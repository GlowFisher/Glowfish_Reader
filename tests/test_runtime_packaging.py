from pathlib import Path


def test_pyinstaller_includes_host_public_package_and_v2_entry():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "glowfish_reader" / "proofread" / "glowfish_reader.spec").read_text(encoding="utf-8")
    assert 'HOST_SRC = os.path.join(HOST_ROOT, "src")' in spec
    assert 'WORKSPACE_ROOT = os.environ.get("GLOWFISH_WORKSPACE_ROOT") or os.path.dirname(HOST_ROOT)' in spec
    assert 'UI_DIST = os.environ.get("GLOWFISH_UI_DIST") or os.path.join(WORKSPACE_ROOT, "ui", "dist")' in spec
    assert 'OCR_COMPONENT = os.environ.get("GLOWFISH_OCR_ROOT") or os.path.join(WORKSPACE_ROOT, "ocr")' in spec
    assert 'OCR_SRC = os.path.join(OCR_COMPONENT, "src")' in spec
    assert "pathex=[HERE, ROOT, PIPELINE, HOST_SRC, OCR_SRC]" in spec
    assert '"glowfish_host", "glowfish_host.app", "glowfish_host.services", "server_v2"' in spec
    assert '"glowfish_ocr", "glowfish_ocr.contracts", "glowfish_ocr.registry"' in spec
    assert '"glowfish_ocr.service", "glowfish_ocr.resident", "glowfish_ocr.validation"' in spec
    assert '"ocr_component_runtime", "ocr_runtime_benchmark", "runtime_status_api", "psutil"' in spec


def test_desktop_exposes_structured_ocr_runtime_benchmark():
    root = Path(__file__).resolve().parents[1]
    desktop = (root / "glowfish_reader" / "proofread" / "desktop_app.py").read_text(encoding="utf-8")
    assert 'if arg1 == "--benchmark-ocr-runtime":' in desktop
    assert "benchmark_main(sys.argv[2:])" in desktop


def test_pyinstaller_excludes_development_only_ml_toolchains():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "glowfish_reader" / "proofread" / "glowfish_reader.spec").read_text(encoding="utf-8")
    assert "PACKAGING_EXCLUDES = [" in spec
    for package in (
        '"torch"', '"transformers"',
        '"onnxruntime.tools"', '"onnxruntime.transformers"',
    ):
        assert package in spec
    assert "excludes=PACKAGING_EXCLUDES" in spec
    assert "_EXCLUDED_MODULE_PREFIXES" in spec
    assert "name.startswith(prefix + \".\")" in spec
    assert '"/onnxruntime/tools/" in combined' in spec
    assert '"/onnxruntime/transformers/" in combined' in spec
    assert 'part.startswith("torch-") and part.endswith(".dist-info")' in spec
    assert "final_datas = [item for item in a.datas if _keep_packaging_item(item)]" in spec
    assert "exe, final_binaries, final_datas" in spec
