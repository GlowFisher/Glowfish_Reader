"""GPU runtime state and manifest validation for the optional OCR provider.

This module deliberately contains no downloader or CUDA import.  The default
application remains CPU-only; a release-specific installer supplies verified
artifacts through the narrow ``install_verified`` method.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import base64
import shutil
import subprocess
import threading
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse
from urllib.request import urlopen
from .cuda_driver import CudaDriverProbe


RUNTIME_STATES = frozenset({
    "not_installed", "incompatible", "downloading", "ready", "active",
    "degraded", "update_required", "error",
})
REASON_CODES = frozenset({
    "no_nvidia_gpu", "unsupported_compute_capability", "insufficient_vram",
    "driver_too_old", "download_failed", "hash_mismatch", "signature_invalid",
    "runtime_selftest_failed", "model_mismatch", "gpu_oom", "cuda_provider_failed",
    "runtime_not_installed", "runtime_manifest_unavailable", "app_version_incompatible",
})


def _version_lt(actual, minimum):
    if not minimum or minimum == "release-defined":
        return False
    try:
        return tuple(map(int, str(actual).split("."))) < tuple(map(int, str(minimum).split(".")))
    except ValueError:
        return True


def _version_in_range(actual, minimum, maximum):
    """Accept dotted numeric ranges and ``x`` wildcards in release manifests."""
    if _version_lt(actual, minimum):
        return False
    actual_parts = str(actual).split(".")
    maximum_parts = str(maximum or "").split(".")
    for index, limit in enumerate(maximum_parts):
        if limit.lower() == "x":
            return True
        try:
            value, ceiling = int(actual_parts[index] if index < len(actual_parts) else 0), int(limit)
        except ValueError:
            return False
        if value < ceiling:
            return True
        if value > ceiling:
            return False
    return len(actual_parts) <= len(maximum_parts)


@dataclass(frozen=True)
class GpuRuntimeManifest:
    runtime_version: str
    protocol_version: int
    min_app_version: str
    max_app_version: str
    artifact_url: str
    artifact_sha256: str
    artifact_size: int
    authenticode_subject: str
    min_compute_capability: str
    min_vram_mb: int
    min_driver_version: str
    supported_engines: tuple[str, ...]
    models_lock_sha256: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "GpuRuntimeManifest":
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported gpu runtime manifest schema")
        artifact, device = payload.get("artifact"), payload.get("device")
        if not isinstance(artifact, Mapping) or not isinstance(device, Mapping):
            raise ValueError("gpu runtime manifest requires artifact and device")
        sha256 = str(artifact.get("sha256") or "").lower()
        if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
            raise ValueError("gpu runtime artifact sha256 must be a 64-character hex digest")
        if urlparse(str(artifact.get("url") or "")).scheme != "https":
            raise ValueError("gpu runtime artifact URL must use HTTPS")
        size = int(artifact.get("size") or 0)
        engines = tuple(str(item) for item in payload.get("supported_engines") or ())
        if size <= 0 or not engines:
            raise ValueError("gpu runtime manifest requires a positive artifact size and supported engines")
        return cls(
            runtime_version=str(payload["runtime_version"]), protocol_version=int(payload["protocol_version"]),
            min_app_version=str(payload["min_app_version"]), max_app_version=str(payload["max_app_version"]),
            artifact_url=str(artifact["url"]), artifact_sha256=sha256, artifact_size=size,
            authenticode_subject=str(artifact["authenticode_subject"]),
            min_compute_capability=str(device["min_compute_capability"]),
            min_vram_mb=int(device["min_vram_mb"]), min_driver_version=str(device["min_driver_version"]),
            supported_engines=engines, models_lock_sha256=str(payload["models_lock_sha256"]),
        )


class GpuRuntimeManager:
    """Owns only local runtime state; download and extraction stay injectable."""

    def __init__(self, root: Path | None = None, *, app_version: str = "0.0.0", device_probe=None):
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        self.root = Path(root or local / "Glowfish Reader" / "gpu-runtime").resolve()
        self.app_version = app_version
        self._lock = threading.RLock()
        self._state = "not_installed"
        self._reason_code = "runtime_not_installed"
        self._device: dict[str, Any] = {}
        self._supported_engines: tuple[str, ...] = ()
        self._download_size: int | None = None
        self._job_id: str | None = None
        self._device_probe = device_probe or CudaDriverProbe()
        self._load_active()

    def refresh_device(self, *, min_compute_capability="7.5", min_vram_mb=5500,
                       min_driver_version=None) -> dict[str, Any]:
        device, reason = self._device_probe.inspect()
        with self._lock:
            if reason:
                self._state, self._reason_code, self._device = "incompatible", reason, {}
            else:
                self._device.update(device)
                if _version_lt(device.get("driver_version"), min_driver_version):
                    self._state, self._reason_code = "incompatible", "driver_too_old"
                elif _version_lt(device.get("compute_capability"), min_compute_capability):
                    self._state, self._reason_code = "incompatible", "unsupported_compute_capability"
                elif int(device.get("vram_mb") or 0) < int(min_vram_mb):
                    self._state, self._reason_code = "incompatible", "insufficient_vram"
                elif self._state == "incompatible":
                    self._state, self._reason_code = "not_installed", "runtime_not_installed"
            return self.status()

    @property
    def active_path(self) -> Path:
        return self.root / "active.json"

    @property
    def previous_path(self) -> Path:
        return self.root / "previous.json"

    def _load_active(self) -> None:
        try:
            active = json.loads(self.active_path.read_text(encoding="utf-8"))
            runtime = str(active["runtime_version"])
            supported_engines = tuple(str(item) for item in active.get("supported_engines") or ())
            download_size = int(active.get("download_size") or 0) or None
        except (OSError, ValueError, KeyError, TypeError):
            return
        self._state, self._reason_code = "ready", None
        self._device = {"runtime_version": runtime}
        self._supported_engines = supported_engines
        self._download_size = download_size

    def status(self, *, preference: str = "cpu") -> dict[str, Any]:
        with self._lock:
            state = self._state
            normalized_preference = preference if preference in {"cpu", "auto"} else "cpu"
            return {
                "preference": normalized_preference,
                "state": state,
                "active_provider": "cuda" if state == "active" and normalized_preference == "auto" else "cpu",
                "device": dict(self._device),
                "driver": self._device.get("driver_version"),
                "vram_mb": self._device.get("vram_mb"),
                "runtime_version": self._device.get("runtime_version"),
                "supported_engines": list(self._supported_engines),
                "download_size": self._download_size,
                "job_id": self._job_id,
                "reason_code": self._reason_code,
            }

    def mark_active(self) -> None:
        """Record a CUDA worker that has completed a real OCR request.

        A saved ``auto`` preference means only that CUDA was requested.  It is
        deliberately insufficient to expose ``active`` to the UI: that state
        is reserved for a worker that has actually produced CUDA output.
        """
        with self._lock:
            if self._state in {"ready", "active"}:
                self._state, self._reason_code, self._job_id = "active", None, None

    def mark_installing(self, job_id: str) -> None:
        with self._lock:
            self._state, self._reason_code, self._job_id = "downloading", None, job_id

    def mark_failure(self, reason_code: str) -> None:
        if reason_code not in REASON_CODES:
            raise ValueError(f"unsupported GPU reason code: {reason_code}")
        with self._lock:
            self._state, self._reason_code, self._job_id = "error", reason_code, None

    def mark_degraded(self, reason_code: str = "cuda_provider_failed") -> None:
        if reason_code not in REASON_CODES:
            raise ValueError(f"unsupported GPU reason code: {reason_code}")
        with self._lock:
            self._state, self._reason_code, self._job_id = "degraded", reason_code, None

    def mark_update_required(self) -> None:
        with self._lock:
            self._state, self._reason_code, self._job_id = "update_required", "app_version_incompatible", None

    def supports_engine(self, engine: str) -> bool:
        with self._lock:
            return str(engine) in self._supported_engines

    def install_verified(self, manifest: GpuRuntimeManifest, runtime_directory: Path) -> None:
        """Atomically activate a runtime already downloaded, verified and self-tested."""
        runtime_directory = Path(runtime_directory).resolve()
        if not runtime_directory.is_dir():
            raise ValueError("verified GPU runtime directory does not exist")
        payload = {
            "runtime_version": manifest.runtime_version,
            "protocol_version": manifest.protocol_version,
            "supported_engines": list(manifest.supported_engines),
            "download_size": manifest.artifact_size,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        if self.active_path.is_file():
            previous = self.previous_path.with_suffix(".json.tmp")
            shutil.copy2(self.active_path, previous)
            previous.replace(self.previous_path)
        temporary = self.active_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(self.active_path)
        with self._lock:
            self._state, self._reason_code, self._job_id = "ready", None, None
            self._device = {"runtime_version": manifest.runtime_version}
            self._supported_engines = manifest.supported_engines
            self._download_size = manifest.artifact_size

    def rollback(self) -> bool:
        """Restore the one retained verified runtime without changing preference."""
        try:
            payload = json.loads(self.previous_path.read_text(encoding="utf-8"))
            runtime_version = str(payload["runtime_version"])
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if not (self.root / "versions" / runtime_version).is_dir():
            return False
        temporary = self.active_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(self.active_path)
        with self._lock:
            self._state, self._reason_code = "ready", None
            self._device = {"runtime_version": runtime_version}
            self._supported_engines = tuple(str(item) for item in payload.get("supported_engines") or ())
            self._download_size = int(payload.get("download_size") or 0) or None
        return True

    def uninstall(self) -> None:
        """Remove every downloaded optional-runtime artifact after its worker stops."""
        with self._lock:
            root = self.root.resolve()
            try:
                self.active_path.unlink()
            except FileNotFoundError:
                pass
            try:
                self.previous_path.unlink()
            except FileNotFoundError:
                pass
            # These are manager-owned directories under the dedicated optional
            # GPU-runtime root.  Do not leave a multi-gigabyte Worker behind
            # after Settings reports it as uninstalled.
            for name in ("versions", "staging", "downloads"):
                target = (root / name).resolve()
                if target.parent != root:
                    raise RuntimeError(f"unsafe GPU runtime uninstall target: {target}")
                if target.exists():
                    shutil.rmtree(target)
            self._state, self._reason_code, self._job_id, self._device, self._supported_engines, self._download_size = (
                "not_installed", "runtime_not_installed", None, {}, (), None)


class GpuRuntimeInstaller:
    """Download and activate a manifest-pinned runtime in one background job.

    This deliberately relies only on the standard library.  Release assembly
    can inject platform-specific Authenticode and GPU smoke-test callbacks.
    """

    def __init__(self, manager: GpuRuntimeManager, *, manifest_url: str | None,
                 models_lock_path: Path | None = None, download=None,
                 models_root: Path | None = None, verify_signature=None, self_test=None):
        self.manager = manager
        self.manifest_url = manifest_url
        self.models_lock_path = Path(models_lock_path) if models_lock_path else None
        self.models_root = Path(models_root) if models_root else None
        self._download = download or self._download_https
        self._verify_signature = verify_signature or self._verify_authenticode
        self._self_test = self_test or self._default_self_test
        self._thread = None
        self._lock = threading.Lock()

    @staticmethod
    def _download_https(url: str, destination: Path) -> None:
        if urlparse(url).scheme != "https":
            raise ValueError("GPU runtime downloads require HTTPS")
        with urlopen(url, timeout=30) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output)

    @staticmethod
    def _verify_authenticode(path: Path, expected_subject: str) -> bool:
        """Validate Windows trust and publisher without interpolating file paths."""
        if os.name != "nt" or not expected_subject:
            return False
        script = (
            "$sig=Get-AuthenticodeSignature -LiteralPath $args[0];"
            "if($sig.Status -ne 'Valid'){exit 2};"
            "$subject=$sig.SignerCertificate.Subject;"
            "if([string]::IsNullOrWhiteSpace($subject) -or "
            "$subject.IndexOf($args[1],[System.StringComparison]::OrdinalIgnoreCase) -lt 0){exit 3};"
            "exit 0"
        )
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded,
                 str(Path(path).resolve()), expected_subject],
                capture_output=True, text=True, timeout=30, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0

    def _default_self_test(self, runtime_dir: Path) -> bool:
        # The frozen worker owns its CUDA/cuDNN loader check.  A release build
        # must ship exactly this executable in the verified archive.
        worker = runtime_dir / "glowfish_gpu_worker.exe"
        if not worker.is_file():
            return False
        command = [str(worker), "--selftest"]
        if self.models_root:
            command.extend(["--models-root", str(self.models_root)])
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
        return completed.returncode == 0 and "GPU SELFTEST OK" in completed.stdout

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def start(self) -> str:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self.manager.status().get("job_id")
            if not self.manifest_url:
                self.manager.mark_failure("runtime_manifest_unavailable")
                return ""
            job_id = uuid.uuid4().hex
            self.manager.mark_installing(job_id)
            self._thread = threading.Thread(target=self._install, name="gpu-runtime-install", daemon=True)
            self._thread.start()
            return job_id

    def _read_manifest(self) -> GpuRuntimeManifest:
        manifest_path = self.manager.root / "downloads" / "gpu-runtime.json.part"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self._download(self.manifest_url, manifest_path)
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            return GpuRuntimeManifest.from_mapping(payload)
        finally:
            manifest_path.unlink(missing_ok=True)

    def _install(self) -> None:
        staging = None
        archive = None
        try:
            manifest = self._read_manifest()
            if not _version_in_range(self.manager.app_version, manifest.min_app_version, manifest.max_app_version):
                self.manager.mark_update_required()
                return
            if self.models_lock_path and self._sha256(self.models_lock_path) != manifest.models_lock_sha256:
                self.manager.mark_failure("model_mismatch")
                return
            downloads = self.manager.root / "downloads"
            archive = downloads / f"{manifest.runtime_version}.zip.part"
            downloads.mkdir(parents=True, exist_ok=True)
            self._download(manifest.artifact_url, archive)
            if archive.stat().st_size != manifest.artifact_size or self._sha256(archive) != manifest.artifact_sha256:
                self.manager.mark_failure("hash_mismatch")
                return
            staging = self.manager.root / "staging" / manifest.runtime_version
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True)
            with zipfile.ZipFile(archive) as bundle:
                target_root = staging.resolve()
                if any((target_root / item.filename).resolve().is_relative_to(target_root) is False for item in bundle.infolist()):
                    raise ValueError("GPU runtime archive contains an unsafe path")
                bundle.extractall(staging)
            worker = staging / "glowfish_gpu_worker.exe"
            if not worker.is_file() or not self._verify_signature(worker, manifest.authenticode_subject):
                self.manager.mark_failure("signature_invalid")
                return
            if not self._self_test(staging):
                self.manager.mark_failure("runtime_selftest_failed")
                return
            target = self.manager.root / "versions" / manifest.runtime_version
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            staging.replace(target)
            staging = None
            self.manager.install_verified(manifest, target)
        except zipfile.BadZipFile as exc:
            logging.getLogger("glowfish.gpu").exception("GPU runtime archive is corrupt: %s", exc)
            self.manager.mark_failure("hash_mismatch")
        except ValueError as exc:
            logging.getLogger("glowfish.gpu").exception("GPU runtime manifest/validation error: %s", exc)
            self.manager.mark_failure("runtime_manifest_unavailable")
        except OSError as exc:
            logging.getLogger("glowfish.gpu").exception("GPU runtime download/IO error: %s", exc)
            self.manager.mark_failure("download_failed")
        except Exception as exc:
            logging.getLogger("glowfish.gpu").exception("GPU runtime install failed unexpectedly: %s", exc)
            self.manager.mark_failure("download_failed")
        finally:
            if archive is not None:
                archive.unlink(missing_ok=True)
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)


def manifest_to_dict(manifest: GpuRuntimeManifest) -> dict[str, Any]:
    return asdict(manifest)
