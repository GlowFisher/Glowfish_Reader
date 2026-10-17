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


def test_exact_recognition_does_not_apply_component_fallback(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "recognize_ppocrv6.py").write_text("# synthetic", encoding="utf-8")
    images = tmp_path / "images"
    images.mkdir()
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)

    service = SubprocessOcrService(legacy, paddle_python=Path("paddle-python"), runner=runner)

    try:
        service.recognize_exact(OcrRequest(images, tmp_path / "result.json", "ppocrv6"))
    except subprocess.CalledProcessError:
        pass
    else:
        raise AssertionError("exact recognition must expose the engine failure")

    assert len(calls) == 1


def test_frozen_desktop_command_uses_ocr_dispatch_protocol(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    images = tmp_path / "images"
    images.mkdir()
    output = tmp_path / "result.json"
    executable = tmp_path / "glowfish-reader.exe"
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        output.write_text(json.dumps({"p001": {"lines": []}}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    service = SubprocessOcrService(legacy, desktop_executable=executable, runner=runner)
    result = service.recognize_exact(OcrRequest(images, output))

    assert result.actual_engine == DEFAULT_ENGINE
    assert calls[0][:3] == [str(executable.resolve()), "--ocr", DEFAULT_ENGINE]
