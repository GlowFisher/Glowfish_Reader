# -*- coding: utf-8 -*-
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_import_engine_switch_uses_shared_engine_preference_helpers():
    settings = (ROOT / "static" / "settings.js").read_text(encoding="utf-8")

    assert 'impEngineFull' in settings
    assert 'impEngineFast' in settings
    assert 'data-engine=""' in settings
    assert 'data-engine="ppocrv6_onnx"' in settings
    assert "function setEnginePreference(value)" in settings
    assert "function syncImportEngineSwitch()" in settings
    assert 'setEnginePreference(v)' in settings
    assert "syncImportEngineSwitch();" in settings
