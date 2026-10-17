from pathlib import Path


def test_ocr_meta_records_provider_runtime_and_timings_without_touching_cache_contract():
    source = (Path(__file__).resolve().parents[1] / "src" / "glowfish_ocr" / "legacy" / "recognize_ppocrv6_onnx.py").read_text(encoding="utf-8")
    assert "def _stamp_provider_meta" in source
    assert '"provider": actual_provider' in source
    assert '"requested_provider": provider' in source
    assert '"runtime_version"' in source
    assert '"stage_timings_ms"' in source
    assert 'cfg.pop("device_name", None)' in source
