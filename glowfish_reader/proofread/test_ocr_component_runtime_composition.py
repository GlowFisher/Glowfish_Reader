import importlib
import sys
from pathlib import Path

import appconfig
import content_api
import ocr_component_runtime


def test_server_v2_installs_component_runner_when_canary_enabled(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "src"))
    monkeypatch.syspath_prepend(str(root / "components" / "ocr" / "src"))
    monkeypatch.setenv("GLOWFISH_OCR_COMPONENT_RUNTIME", "1")
    monkeypatch.setattr(appconfig, "data_root", lambda: tmp_path)
    sys.modules.pop("server_v2", None)

    try:
        runtime = importlib.import_module("server_v2")
        assert runtime.OCR_RUNTIME == "component"
        assert isinstance(
            content_api._OCR_ENGINE_RUNNER,
            ocr_component_runtime.ComponentOcrEngineRunner,
        )
    finally:
        content_api.configure_ocr_engine_runner(None)
        sys.modules.pop("server_v2", None)
