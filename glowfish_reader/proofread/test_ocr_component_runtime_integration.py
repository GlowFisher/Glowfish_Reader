import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import ocr_component_runtime


def test_default_runner_executes_public_component_exact_service(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "components" / "ocr" / "src"))
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(ocr_component_runtime.appconfig, "get_paddle_python", lambda: None)
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        output = Path(command[command.index("--out") + 1])
        output.write_text('{"p001": {"lines": []}}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(ocr_component_runtime.windows_process, "run", fake_run)
    output = tmp_path / "recog.json"
    runner = ocr_component_runtime.ComponentOcrEngineRunner()

    assert runner(
        ctx=SimpleNamespace(progress_path=tmp_path / "progress.json"),
        image_dir=tmp_path,
        recog_path=output,
        engine="ppocrv6_onnx_high",
    )

    assert output.exists()
    assert captured["command"][0] == sys.executable
    assert captured["command"][1].endswith("recognize_ppocrv6_onnx.py")
    assert captured["kwargs"]["purpose"] == "component-ocr"
