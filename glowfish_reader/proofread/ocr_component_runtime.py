"""Opt-in adapter from the legacy content route to the public OCR component."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import appconfig
import subprocess_env
import windows_process


_TRUE_VALUES = {"1", "true", "yes", "on"}
_HERE = Path(__file__).resolve().parent


def component_runtime_enabled(value: str | None = None) -> bool:
    if value is None:
        value = os.environ.get("GLOWFISH_OCR_COMPONENT_RUNTIME")
    return str(value or "").strip().lower() in _TRUE_VALUES


def _idle_ttl_seconds() -> float:
    try:
        return float(os.environ.get("SHUPAI_OCR_IDLE_TTL", "180"))
    except ValueError:
        return 180.0


def _default_worker_factory(prefix, **kwargs):
    from glowfish_ocr import JsonLineOcrWorker

    return JsonLineOcrWorker(
        prefix,
        spawn=windows_process.spawn,
        terminate=windows_process.terminate_process,
        **kwargs,
    )


def _default_service_factory(job=None):
    from glowfish_ocr import ResidentOcrService

    desktop_executable = Path(sys.executable) if getattr(sys, "frozen", False) else None
    return ResidentOcrService(
        legacy_dir=_HERE,
        paddle_python=appconfig.get_paddle_python(),
        desktop_executable=desktop_executable,
        env=subprocess_env.clean_subprocess_env(),
        worker_factory=_default_worker_factory,
        idle_ttl_seconds=_idle_ttl_seconds(),
    )


def _default_request_factory(**kwargs):
    from glowfish_ocr import OcrRequest

    return OcrRequest(**kwargs)


class ComponentOcrEngineRunner:
    """Translate one Host engine attempt into the public component contract."""

    def __init__(self, service_factory=None, request_factory=None):
        self._service_factory = service_factory or _default_service_factory
        self._request_factory = request_factory or _default_request_factory
        self._service_lock = threading.Lock()
        self._service = None

    def _service_for(self, job=None):
        with self._service_lock:
            if self._service is None:
                self._service = self._service_factory(job)
            return self._service

    def __call__(self, *, ctx, image_dir, recog_path, engine, job=None):
        if job is not None:
            job.check_cancelled()
        progress_path = getattr(job, "progress_path", None) or ctx.progress_path
        request = self._request_factory(
            image_dir=Path(image_dir),
            output_path=Path(recog_path),
            engine=engine,
            progress_path=Path(progress_path),
            job_id=getattr(job, "job_id", None),
        )
        self._service_for(job).recognize_exact(request)
        if job is not None:
            job.check_cancelled()
        return True

    def prewarm(self, engine: str) -> bool:
        return self._service_for().prewarm(engine).ok

    def shutdown(self) -> None:
        with self._service_lock:
            service, self._service = self._service, None
        if service is not None:
            service.shutdown()
