from pathlib import Path


PROOFREAD = Path(__file__).resolve().parents[1] / "glowfish_reader" / "proofread"


def test_runtime_never_invokes_subst():
    runtime_files = (
        PROOFREAD / "paddlex_cache.py",
        PROOFREAD / "recognize_ppocrv6.py",
        PROOFREAD / "recognize_ppocrv6_onnx.py",
    )

    for path in runtime_files:
        source = path.read_text(encoding="utf-8")
        assert '["subst"' not in source
        assert "['subst'" not in source
