import importlib.util
import sys
import types
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "verify_gpu_runtime_build.py"
SPEC = importlib.util.spec_from_file_location("gpu_runtime_build_verifier", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _lock(*, release_qualified=True):
    return {
        "schema_version": 1,
        "label": "test-lock",
        "release_qualified": release_qualified,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "packages": {"test-gpu-package": "1.2.3"},
        "required_provider": "CUDAExecutionProvider",
    }


def test_verify_reports_pinned_environment(monkeypatch):
    monkeypatch.setattr(MODULE, "_version", lambda name: "1.2.3")
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        types.SimpleNamespace(get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"]),
    )

    report = MODULE.verify(_lock(), require_release_qualified=True)

    assert report["release_qualified"] is True
    assert report["packages"] == {"test-gpu-package": "1.2.3"}
    assert "CUDAExecutionProvider" in report["providers"]


def test_verify_refuses_candidate_lock_for_release():
    with pytest.raises(RuntimeError, match="candidate-only"):
        MODULE.verify(_lock(release_qualified=False), require_release_qualified=True)


def test_verify_refuses_missing_cuda_provider(monkeypatch):
    monkeypatch.setattr(MODULE, "_version", lambda name: "1.2.3")
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        types.SimpleNamespace(get_available_providers=lambda: ["CPUExecutionProvider"]),
    )

    with pytest.raises(RuntimeError, match="required ONNX Runtime provider is unavailable"):
        MODULE.verify(_lock())
