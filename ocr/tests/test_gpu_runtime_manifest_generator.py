import importlib.util
import zipfile
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "generate_gpu_runtime_manifest.py"
SPEC = importlib.util.spec_from_file_location("gpu_runtime_manifest_generator", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_runtime_archive_accepts_only_the_worker(tmp_path):
    archive = tmp_path / "runtime.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("glowfish_gpu_worker.exe", b"worker")
    MODULE.validate_runtime_archive(archive)


@pytest.mark.parametrize("name", ["models/rec/inference.onnx", "nested/glowfish_gpu_worker.exe", "../glowfish_gpu_worker.exe"])
def test_runtime_archive_rejects_duplicate_models_or_unsafe_layout(tmp_path, name):
    archive = tmp_path / "runtime.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("glowfish_gpu_worker.exe", b"worker")
        bundle.writestr(name, b"unexpected")
    with pytest.raises(ValueError):
        MODULE.validate_runtime_archive(archive)
