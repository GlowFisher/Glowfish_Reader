from pathlib import Path


DESKTOP_APP = (
    Path(__file__).resolve().parents[1]
    / "glowfish_reader"
    / "proofread"
    / "desktop_app.py"
)


def test_frozen_resident_worker_restores_inherited_stdio_before_hardening():
    text = DESKTOP_APP.read_text(encoding="utf-8")

    helper = text.index("def _restore_frozen_worker_stdio():")
    call = text.index("_restore_frozen_worker_stdio()", helper + 1)
    harden = text.index("_harden_std()", call)

    assert helper < call < harden
    assert 'and "--ocr" in sys.argv' in text
    assert 'and "--serve-worker" in sys.argv' in text
    assert "GetStdHandle" in text
    assert "msvcrt.open_osfhandle" in text
    assert 'bind("stdin", -10' in text
    assert 'bind("stdout", -11' in text
