# -*- coding: utf-8 -*-
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_import_engine_switch_uses_shared_preference_helpers_and_modal_scope():
    settings = (ROOT / "src" / "settings.js").read_text(encoding="utf-8")
    html = (ROOT / "src" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "src" / "style.css").read_text(encoding="utf-8")

    assert '["ppocrv6_onnx", "\u5feb\u901f\u7248"]' in settings
    assert "function setEnginePreference(value)" in settings
    assert 'settings.engine_pref = value || "";' in settings
    assert "persistEnginePreference();" in settings
    assert "updateSegBtns();" in settings
    assert "function syncImportEngineSwitch()" in settings
    assert 'document.querySelector("#importModal")' in settings
    assert "if (!importModal) return;" in settings
    assert 'importModal.querySelectorAll("[data-engine]")' in settings
    assert 'setEnginePreference(v)' in settings
    assert "updateSegBtns(); syncImportEngineSwitch(); applyAllSettings();" in settings

    assert html.count('class="btn btn-sec imp-sort-btn"') == 5
    assert html.index('data-sort="reverse"') < html.index('id="impEngineFull"')
    assert 'class="imp-engine-switch"' in html
    assert ".imp-toolbar .imp-sort-btn" in css
    assert ".imp-engine-switch" in css
