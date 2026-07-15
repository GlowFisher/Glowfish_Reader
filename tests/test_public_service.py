import json
import subprocess
from pathlib import Path

from glowfish_ocr import OcrRequest, SubprocessOcrService
from glowfish_ocr.registry import DEFAULT_ENGINE, LIGHTWEIGHT_ENGINE, normalize_engine


def test_engine_alias_and_default_are_stable():
    assert normalize_engine(None) == DEFAULT_ENGINE
    assert normalize_engine("") == DEFAULT_ENGINE
    assert normalize_engine("onnx") == LIGHTWEIGHT_ENGINE
    assert normalize_engine("unknown") == DEFAULT_ENGINE


def test_service_validates_v1_output(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "recognize_ppocrv6_onnx.py").write_text("# synthetic", encoding="utf-8")
    images = tmp_path / "images"
    images.mkdir()
    output = tmp_path / "result.json"

    def runner(command, **kwargs):
        output.write_text(json.dumps({
            "p001": {"image": "p001.png", "width": 1, "height": 1,
                     "lines": [{"text": "x", "box": [0, 0, 1, 1], "score": 1.0}]}
        }), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    service = SubprocessOcrService(legacy, runner=runner)
    result = service.recognize(OcrRequest(images, output, "onnx"))
    assert result.actual_engine == LIGHTWEIGHT_ENGINE
    assert result.pages["p001"]["lines"][0]["text"] == "x"


def test_service_falls_back_to_lightweight(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    for name in ["recognize_ppocrv6_onnx.py", "recognize_ppocrv6.py"]:
        (legacy / name).write_text("# synthetic", encoding="utf-8")
    images = tmp_path / "images"
    images.mkdir()
    output = tmp_path / "result.json"
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, command)
        output.write_text(json.dumps({"p001": {"image": "x", "width": 1, "height": 1, "lines": []}}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    service = SubprocessOcrService(legacy, paddle_python=Path("paddle-python"), runner=runner)
    result = service.recognize(OcrRequest(images, output, "ppocrv6"))
    assert result.actual_engine == LIGHTWEIGHT_ENGINE
    assert result.fallback.startswith("ppocrv6:")
    assert len(calls) == 2
