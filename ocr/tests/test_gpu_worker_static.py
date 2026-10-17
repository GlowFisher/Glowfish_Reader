from pathlib import Path


def test_gpu_worker_uses_the_locked_onnx_pipeline_and_strict_cuda_selftest():
    root = Path(__file__).resolve().parents[1] / "src" / "glowfish_ocr" / "legacy"
    worker = (root / "gpu_worker.py").read_text(encoding="utf-8")
    recognizer = (root / "recognize_ppocrv6_onnx.py").read_text(encoding="utf-8")
    assert "from recognize_ppocrv6_onnx import main" in worker
    assert 'if provider == "cuda":' in recognizer
    assert "def gpu_selftest" in recognizer
    assert "CUDA provider did not become active" in recognizer
