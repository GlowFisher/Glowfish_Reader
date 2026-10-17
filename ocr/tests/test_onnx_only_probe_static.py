from pathlib import Path


def test_onnx_only_probe_does_not_import_paddle_stack():
    source = (Path(__file__).parents[1] / "src" / "glowfish_ocr" / "legacy" / "onnx_only_ocr_probe.py").read_text(encoding="utf-8")
    assert "import paddle" not in source
    assert "import paddlex" not in source
    assert "CUDAExecutionProvider did not load" in source
    assert "os.add_dll_directory" in source
    assert "--baseline-json" in source
    assert "parity rejected" in source
