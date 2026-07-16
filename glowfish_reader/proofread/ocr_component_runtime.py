"""Opt-in adapter from the legacy content route to the public OCR component."""

from __future__ import annotations

import os
import subprocess
import sys
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


def _tracked_process_runner(job=None):
    job_id = getattr(job, "job_id", None)

    def run(command, *, check=False, timeout=None, cwd=None):
        result = windows_process.run(
            command,
            purpose="component-ocr",
            job_id=job_id,
            timeout=timeout,
            cwd=cwd,
            env=subprocess_env.clean_subprocess_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                command,
                output=result.stdout,
                stderr=result.stderr,
            )
        return result

    return run


def _default_service_factory(job=None):
    from glowfish_ocr import SubprocessOcrService

    desktop_executable = Path(sys.executable) if getattr(sys, "frozen", False) else None
    return SubprocessOcrService(
        legacy_dir=_HERE,
        paddle_python=appconfig.get_paddle_python(),
        desktop_executable=desktop_executable,
        runner=_tracked_process_runner(job),
    )


def _default_request_factory(**kwargs):
    from glowfish_ocr import OcrRequest

    return OcrRequest(**kwargs)


class ComponentOcrEngineRunner:
    """Translate one Host engine attempt into the public component contract."""

    def __init__(self, service_factory=None, request_factory=None):
        self._service_factory = service_factory or _default_service_factory
        self._request_factory = request_factory or _default_request_factory

    def __call__(self, *, ctx, image_dir, recog_path, engine, job=None):
        if job is not None:
            job.check_cancelled()
        progress_path = getattr(job, "progress_path", None) or ctx.progress_path
        request = self._request_factory(
            image_dir=Path(image_dir),
            output_path=Path(recog_path),
            engine=engine,
            progress_path=Path(progress_path),
        )
        self._service_factory(job).recognize_exact(request)
        if job is not None:
            job.check_cancelled()
        return True
