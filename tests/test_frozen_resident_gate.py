from pathlib import Path


DESKTOP_APP = (
    Path(__file__).resolve().parents[1]
    / "glowfish_reader"
    / "proofread"
    / "desktop_app.py"
)


def test_frozen_resident_gate_uses_component_worker_and_unicode_long_path():
    text = DESKTOP_APP.read_text(encoding="utf-8")

    assert 'arg1 == "--selftest-ocr-resident"' in text
    assert "ComponentOcrEngineRunner()" in text
    assert '"\\u4e2d\\u6587 path with spaces"' in text
    assert '"long-path-" * 8' in text
    assert 'worker.get("alive")' in text
    assert 'status.get("one_shot_fallback")' in text
