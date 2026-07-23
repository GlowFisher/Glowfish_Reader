from pathlib import Path


LEGACY = Path(__file__).resolve().parents[1] / "src" / "glowfish_ocr" / "legacy"


def test_runtime_never_invokes_subst():
    runtime_files = (
        LEGACY / "paddlex_cache.py",
        LEGACY / "recognize_ppocrv6.py",
        LEGACY / "recognize_ppocrv6_onnx.py",
    )

    for path in runtime_files:
        source = path.read_text(encoding="utf-8")
        assert '["subst"' not in source
        assert "['subst'" not in source
