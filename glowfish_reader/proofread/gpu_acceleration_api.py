"""Per-user bridge for the optional GPU runtime component."""

import os
import json
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from glowfish_host import GpuRuntimeInstaller, GpuRuntimeManager
from settings_store import load_settings, save_settings
from userctx import Ctx, ctx_dep

router = APIRouter()
_RUNTIME = GpuRuntimeManager(app_version="1.0.3")
_MODELS_LOCK = Path(__file__).resolve().parents[3] / "ocr" / "models.lock.json"


def _first_existing(candidates):
    return next((path for path in candidates if path.is_dir()), candidates[0])


_HERE = Path(__file__).resolve().parent
_EXECUTABLE_DIR = Path(sys.executable).resolve().parent
_MODELS_ROOT = _first_existing((
    _HERE / "models",                         # frozen desktop bundle
    _EXECUTABLE_DIR / "_internal" / "models",  # frozen executable entry
    _HERE.parents[2] / ".build" / "dist" / "glowfish_reader" / "_internal" / "models",
))


def _find_trial_python():
    explicit = os.environ.get("GLOWFISH_GPU_TRIAL_PY")
    if explicit:
        return Path(explicit)
    for ancestor in (_HERE, *_HERE.parents, _EXECUTABLE_DIR, *_EXECUTABLE_DIR.parents):
        candidate = ancestor / ".runtime" / "gpu-trial" / "Scripts" / "python.exe"
        if candidate.is_file():
            return candidate
    return _HERE / ".runtime" / "gpu-trial" / "Scripts" / "python.exe"


_TRIAL_PYTHON = _find_trial_python()
_TRIAL_MODELS = _MODELS_ROOT
_TRIAL_WORKSPACE = _TRIAL_PYTHON.parents[3] if _TRIAL_PYTHON.is_file() else Path()
_TRIAL_OCR_ROOT = _TRIAL_WORKSPACE / "github-main" / "ocr"
_TRIAL_SCRIPT = _TRIAL_OCR_ROOT / "src" / "glowfish_ocr" / "legacy" / "recognize_ppocrv6_onnx.py"
_TRIAL_ACTIVE = False


def _trial_ready():
    return _TRIAL_PYTHON.is_file() and _TRIAL_MODELS.is_dir() and _TRIAL_SCRIPT.is_file()
_INSTALLER = GpuRuntimeInstaller(
    _RUNTIME,
    manifest_url=os.environ.get("GLOWFISH_GPU_RUNTIME_MANIFEST"),
    models_lock_path=_MODELS_LOCK if _MODELS_LOCK.is_file() else None,
    models_root=_MODELS_ROOT if _MODELS_ROOT.is_dir() else None,
)


def _preference(ctx):
    return load_settings(ctx).get("ocr_acceleration", "cpu")


def _status(ctx):
    global _TRIAL_ACTIVE
    _RUNTIME.refresh_device()
    status = _RUNTIME.status(preference=_preference(ctx))
    if _trial_ready():
        enabled = _preference(ctx) == "auto" and _TRIAL_ACTIVE
        status.update(
            state="active" if enabled else "ready",
            active_provider="cuda" if enabled else "cpu",
            runtime_version="local-trial",
            reason_code=None if enabled else status.get("reason_code"),
        )
    return status


def _trial_self_test():
    """Fail closed: opting in must load the locked models through CUDA once."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(_TRIAL_OCR_ROOT / "src"), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    completed = subprocess.run(
        [str(_TRIAL_PYTHON), str(_TRIAL_SCRIPT), "--selftest", "--models-root", str(_TRIAL_MODELS)],
        env=env, capture_output=True, text=True, timeout=180, check=False,
    )
    if completed.returncode != 0 or "GPU SELFTEST OK" not in completed.stdout:
        detail = (completed.stderr or completed.stdout or "CUDA self-test failed").strip()[:500]
        raise RuntimeError(detail)


def execution_config(ctx, engine):
    """Return the provider contract for one OCR attempt, fail-closed to CPU."""
    status = _status(ctx)
    # A saved runtime is not permission to keep using CUDA.  The Settings
    # "使用 CPU" action must take effect on the very next OCR request without
    # forcing a multi-gigabyte runtime download on a later re-enable.
    if _preference(ctx) != "auto":
        return {"provider": "cpu"}
    if status.get("runtime_version") == "local-trial" and _preference(ctx) == "auto":
        return {
            "provider": "cuda", "gpu_python": str(_TRIAL_PYTHON),
            "gpu_runtime_version": "local-trial", "model_root": str(_TRIAL_MODELS),
            "gpu_script": str(_TRIAL_SCRIPT),
            "gpu_pythonpath": str(_TRIAL_OCR_ROOT / "src"),
            "engine_profile": str(engine), "device_name": (status.get("device") or {}).get("name"),
        }
    if status["state"] != "active":
        return {"provider": "cpu"}
    if not _RUNTIME.supports_engine(engine):
        return {"provider": "cpu"}
    runtime_version = str(status.get("runtime_version") or "")
    runtime_dir = _RUNTIME.root / "versions" / runtime_version
    worker = runtime_dir / "glowfish_gpu_worker.exe"
    if not runtime_version or not worker.is_file():
        return {"provider": "cpu"}
    return {
        "provider": "cuda",
        "gpu_runtime_dir": str(runtime_dir),
        "gpu_runtime_version": runtime_version,
        "model_root": str(Path(__file__).resolve().parent / "models"),
        "engine_profile": str(engine),
        "device_name": (status.get("device") or {}).get("name"),
    }


def report_execution_failure(ctx, error):
    """Keep the opt-in preference but force this session back to CPU."""
    global _TRIAL_ACTIVE
    _TRIAL_ACTIVE = False
    _RUNTIME.mark_degraded("gpu_oom" if "oom" in str(error).lower() else "cuda_provider_failed")


def report_execution_success(ctx, config, recog_path):
    """Promote status only after the Worker has emitted CUDA page metadata."""
    global _TRIAL_ACTIVE
    if config.get("provider") != "cuda":
        return
    try:
        payload = json.loads(Path(recog_path).read_text(encoding="utf-8"))
        pages = [page for key, page in payload.items() if key != "_meta" and isinstance(page, dict)]
        if not pages or any((page.get("ocr_meta") or {}).get("provider") != "cuda" for page in pages):
            raise RuntimeError("CUDA worker returned non-CUDA OCR metadata")
    except Exception as exc:
        report_execution_failure(ctx, exc)
        raise
    if config.get("gpu_runtime_version") == "local-trial":
        _TRIAL_ACTIVE = True
    else:
        _RUNTIME.mark_active()


@router.get("/api/ocr/acceleration")
def get_acceleration(ctx: Ctx = Depends(ctx_dep)):
    return _status(ctx)


@router.post("/api/ocr/acceleration/install")
def install_acceleration(ctx: Ctx = Depends(ctx_dep)):
    """Start one manifest-pinned install job, or report why it is unavailable."""
    if _status(ctx)["state"] == "incompatible":
        return _status(ctx)
    job_id = _INSTALLER.start()
    result = _status(ctx)
    result["job_id"] = job_id or result.get("job_id")
    return result


@router.get("/api/ocr/acceleration/install/status")
def acceleration_install_status(ctx: Ctx = Depends(ctx_dep)):
    return _status(ctx)


@router.post("/api/ocr/acceleration/enable")
def enable_acceleration(ctx: Ctx = Depends(ctx_dep)):
    local_trial_ready = _trial_ready()
    if not local_trial_ready and _status(ctx)["state"] not in {"ready", "active"}:
        raise HTTPException(409, "runtime_not_ready")
    if local_trial_ready:
        try:
            _trial_self_test()
        except Exception as exc:
            report_execution_failure(ctx, exc)
            raise HTTPException(409, "runtime_selftest_failed") from exc
    settings = load_settings(ctx)
    settings["ocr_acceleration"] = "auto"
    save_settings(ctx, settings)
    return _status(ctx)


@router.post("/api/ocr/acceleration/disable")
def disable_acceleration(ctx: Ctx = Depends(ctx_dep)):
    """Switch future OCR requests to CPU but retain the optional runtime."""
    global _TRIAL_ACTIVE
    _TRIAL_ACTIVE = False
    settings = load_settings(ctx)
    settings["ocr_acceleration"] = "cpu"
    save_settings(ctx, settings)
    return _status(ctx)


@router.delete("/api/ocr/acceleration")
def uninstall_acceleration(ctx: Ctx = Depends(ctx_dep)):
    settings = load_settings(ctx)
    settings["ocr_acceleration"] = "cpu"
    save_settings(ctx, settings)
    _RUNTIME.uninstall()
    return _status(ctx)
