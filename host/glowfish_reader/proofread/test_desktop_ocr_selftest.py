# -*- coding: utf-8 -*-
import json
import sys
import types

import desktop_app


def _prepare_fixture(monkeypatch, tmp_path):
    fixture = tmp_path / "assets" / "selftest" / "vertical_cht_clean.png"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"not-a-real-image-for-the-stub")
    monkeypatch.setattr(desktop_app, "HERE", tmp_path)


def test_selftest_ocr_runs_both_presets_and_requires_nonempty_lines(monkeypatch, tmp_path):
    _prepare_fixture(monkeypatch, tmp_path)
    calls = []

    def build(config):
        calls.append(("build", dict(config)))
        return object()

    def run_job(engine, images, out, **kwargs):
        calls.append(("run", dict(kwargs.get("config") or {})))
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"page1": {"lines": [{"text": "测"}]}}, f)
        return 1, 0

    monkeypatch.setitem(sys.modules, "recognize_ppocrv6_onnx", types.SimpleNamespace(
        _build_engine=build, run_job=run_job,
    ))

    assert desktop_app._selftest_ocr() == 0
    configs = [entry[1] for entry in calls if entry[0] == "build"]
    assert any(config.get("profile") == "high_accuracy" for config in configs)
    assert any(config.get("text_det_limit_side_len") == 960 for config in configs)


def test_selftest_ocr_fails_when_any_preset_has_no_lines(monkeypatch, tmp_path):
    _prepare_fixture(monkeypatch, tmp_path)

    def run_job(engine, images, out, **kwargs):
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"page1": {"lines": []}}, f)
        return 1, 0

    monkeypatch.setitem(sys.modules, "recognize_ppocrv6_onnx", types.SimpleNamespace(
        _build_engine=lambda config: object(), run_job=run_job,
    ))

    assert desktop_app._selftest_ocr() == 1


def test_selftest_ocr_deps_uses_paddlex_runtime_check(monkeypatch):
    from paddlex.utils import deps

    monkeypatch.setitem(deps.EXTRAS, "ocr-core", {"imagesize": [], "python-bidi": []})
    monkeypatch.setattr(deps, "is_dep_available", lambda name: name == "imagesize")

    assert desktop_app._selftest_ocr_deps() == 1
