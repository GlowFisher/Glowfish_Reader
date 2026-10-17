import json
import hashlib
import zipfile

import pytest

from glowfish_host.acceleration import GpuRuntimeInstaller, GpuRuntimeManager, GpuRuntimeManifest, _version_in_range


class Probe:
    def __init__(self, device, reason=None): self.device, self.reason = device, reason
    def inspect(self): return self.device, self.reason


def _manifest():
    return GpuRuntimeManifest.from_mapping({
        "schema_version": 1,
        "runtime_version": "1.0.0",
        "protocol_version": 2,
        "min_app_version": "1.0.0",
        "max_app_version": "1.0.99",
        "artifact": {
            "url": "https://releases.example.invalid/gpu.zip",
            "sha256": "a" * 64,
            "size": 1024,
            "authenticode_subject": "Glowfish Reader",
        },
        "device": {"min_compute_capability": "7.5", "min_vram_mb": 6144, "min_driver_version": "1.0"},
        "supported_engines": ["ppocrv6_onnx", "ppocrv6_onnx_high"],
        "models_lock_sha256": "models-lock",
    })


def test_gpu_runtime_is_cpu_only_until_a_verified_runtime_is_activated(tmp_path):
    manager = GpuRuntimeManager(tmp_path / "gpu-runtime")
    assert manager.status()["state"] == "not_installed"
    assert manager.status()["active_provider"] == "cpu"

    runtime = tmp_path / "verified"
    runtime.mkdir()
    manager.install_verified(_manifest(), runtime)

    assert manager.status()["state"] == "ready"
    assert manager.status(preference="auto")["state"] == "ready"
    assert manager.status(preference="auto")["active_provider"] == "cpu"
    manager.mark_active()
    assert manager.status(preference="auto")["state"] == "active"
    assert manager.status(preference="auto")["active_provider"] == "cuda"
    assert manager.status(preference="cpu")["active_provider"] == "cpu"
    assert manager.status()["download_size"] == 1024
    assert manager.supports_engine("ppocrv6_onnx")
    assert not manager.supports_engine("paddle")
    assert json.loads((tmp_path / "gpu-runtime" / "active.json").read_text())["runtime_version"] == "1.0.0"
    manager.mark_degraded()
    assert manager.status(preference="auto")["state"] == "degraded"
    assert manager.status(preference="auto")["active_provider"] == "cpu"


def test_manifest_rejects_an_unpinned_artifact():
    payload = {
        "schema_version": 1, "runtime_version": "1", "protocol_version": 2,
        "min_app_version": "1", "max_app_version": "1", "artifact": {"url": "x", "sha256": "bad", "size": 1, "authenticode_subject": "Glowfish Reader"},
        "device": {"min_compute_capability": "7.5", "min_vram_mb": 6144, "min_driver_version": "1"},
        "supported_engines": ["ppocrv6_onnx"], "models_lock_sha256": "lock",
    }
    with pytest.raises(ValueError, match="sha256"):
        GpuRuntimeManifest.from_mapping(payload)


def test_manifest_app_version_range_honours_numeric_limits_and_wildcards():
    assert _version_in_range("1.0.3", "1.0.0", "1.0.99")
    assert _version_in_range("1.4.0", "1.0.0", "1.x.y")
    assert not _version_in_range("2.0.0", "1.0.0", "1.x.y")
    assert not _version_in_range("0.9.9", "1.0.0", "1.x.y")


def test_device_gate_reports_stable_incompatibility_codes(tmp_path):
    manager = GpuRuntimeManager(tmp_path / "gpu", device_probe=Probe(None, "no_nvidia_gpu"))
    assert manager.refresh_device()["reason_code"] == "no_nvidia_gpu"
    manager = GpuRuntimeManager(tmp_path / "gpu2", device_probe=Probe({
        "name": "RTX", "compute_capability": "7.5", "vram_mb": 4096, "driver_version": "12.4"}))
    assert manager.refresh_device()["reason_code"] == "insufficient_vram"


def test_device_gate_rejects_an_old_driver_before_gpu_is_requested(tmp_path):
    manager = GpuRuntimeManager(tmp_path / "gpu", device_probe=Probe({
        "name": "RTX", "compute_capability": "7.5", "vram_mb": 8192, "driver_version": "11.8",
    }))
    status = manager.refresh_device(min_driver_version="12.0")
    assert status["state"] == "incompatible"
    assert status["reason_code"] == "driver_too_old"
    assert status["active_provider"] == "cpu"


@pytest.mark.parametrize("reason", ["cuda_provider_failed", "gpu_oom"])
def test_cuda_runtime_failures_always_degrade_to_cpu(tmp_path, reason):
    manager = GpuRuntimeManager(tmp_path / "gpu-runtime")
    runtime = tmp_path / "verified"
    runtime.mkdir()
    manager.install_verified(_manifest(), runtime)
    manager.mark_active()
    manager.mark_degraded(reason)
    status = manager.status(preference="auto")
    assert status["state"] == "degraded"
    assert status["reason_code"] == reason
    assert status["active_provider"] == "cpu"


def test_runtime_manager_keeps_one_version_for_atomic_rollback(tmp_path):
    manager = GpuRuntimeManager(tmp_path / "gpu-runtime")
    first = manager.root / "versions" / "1.0.0"
    second = manager.root / "versions" / "1.0.1"
    first.mkdir(parents=True); second.mkdir(parents=True)
    manager.install_verified(_manifest(), first)
    payload = _manifest().__dict__ | {"runtime_version": "1.0.1"}
    manager.install_verified(GpuRuntimeManifest(**payload), second)
    assert manager.status()["runtime_version"] == "1.0.1"
    assert manager.rollback()
    assert manager.status()["runtime_version"] == "1.0.0"


def test_uninstall_removes_all_downloaded_runtime_artifacts(tmp_path):
    manager = GpuRuntimeManager(tmp_path / "gpu-runtime")
    runtime = manager.root / "versions" / "1.0.0"
    runtime.mkdir(parents=True)
    (runtime / "glowfish_gpu_worker.exe").write_bytes(b"worker")
    (manager.root / "downloads").mkdir()
    (manager.root / "downloads" / "runtime.zip.part").write_bytes(b"archive")
    manager.install_verified(_manifest(), runtime)

    manager.uninstall()

    assert not (manager.root / "versions").exists()
    assert not (manager.root / "downloads").exists()
    assert manager.status()["state"] == "not_installed"


def test_installer_activates_only_a_verified_archive(tmp_path):
    archive = tmp_path / "runtime.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("glowfish_gpu_worker.exe", b"worker")
    payload = {
        "schema_version": 1, "runtime_version": "1.0.0", "protocol_version": 2,
        "min_app_version": "1.0.0", "max_app_version": "1.0.99",
        "artifact": {"url": "https://release.invalid/runtime.zip", "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "size": archive.stat().st_size, "authenticode_subject": "Glowfish Reader"},
        "device": {"min_compute_capability": "7.5", "min_vram_mb": 6144, "min_driver_version": "1.0"},
        "supported_engines": ["ppocrv6_onnx"], "models_lock_sha256": "lock",
    }

    def download(url, destination):
        if url.endswith("manifest.json"):
            destination.write_text(json.dumps(payload), encoding="utf-8")
        else:
            destination.write_bytes(archive.read_bytes())

    manager = GpuRuntimeManager(tmp_path / "gpu-runtime", app_version="1.0.3")
    installer = GpuRuntimeInstaller(
        manager, manifest_url="https://release.invalid/manifest.json", download=download,
        verify_signature=lambda _path, _subject: True, self_test=lambda _path: True,
    )
    installer._install()
    assert manager.status()["state"] == "ready"
    assert (manager.root / "versions" / "1.0.0" / "glowfish_gpu_worker.exe").is_file()
