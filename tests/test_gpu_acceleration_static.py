from pathlib import Path


def _read(name):
    return (Path(__file__).resolve().parents[1] / "src" / name).read_text(encoding="utf-8")


def test_settings_exposes_an_explicit_gpu_experimental_card():
    settings = _read("settings.js")
    assert "GPU 加速（实验功能）" in settings
    assert "renderGpuAccelerationCard" in settings
    assert 'ocr_acceleration: "cpu"' in settings
    assert "安装组件" in settings
    assert "启用 GPU" in settings
    assert "使用 CPU" in settings
    assert "卸载组件" in settings


def test_ocr_api_has_no_implicit_gpu_download_call():
    api = _read("api/ocr-api.js")
    assert "installAcceleration" in api
    assert '"/api/ocr/acceleration/install"' in api
    assert "disableAcceleration" in api
    assert '"/api/ocr/acceleration/disable"' in api
