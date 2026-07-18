"""Opt-in adapter from the legacy content route to the public OCR component."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

import appconfig
import subprocess_env
import windows_process


_TRUE_VALUES = {"1", "true", "yes", "on"}
_COMPONENT_VALUES = _TRUE_VALUES | {"component"}
_HERE = Path(__file__).resolve().parent
_LOG = logging.getLogger("glowfish.ocr.component")


def component_runtime_mode(value: str | None = None) -> str:
    if value is None:
        value = os.environ.get("GLOWFISH_OCR_COMPONENT_RUNTIME")
    normalized = str(value or "").strip().lower()
    if normalized in {"legacy", "0", "false", "no", "off"}:
        return "legacy"

    return "component"

def component_runtime_enabled(value: str | None = None) -> bool:
    return component_runtime_mode(value) == "component"


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


class OcrRuntimeMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._values = {
            "component_attempts": 0,
            "component_successes": 0,
            "component_failures": 0,
            "component_duration_ms": 0,
            "prewarm_attempts": 0,
            "prewarm_successes": 0,
            "prewarm_failures": 0,
            "fallback_attempts": 0,
            "fallback_successes": 0,
            "fallback_failures": 0,
            "last_event": None,
            "last_engine": None,
            "last_error_type": None,
            "last_event_at": None,
        }

    def _record(self, event, engine, *, success, duration_ms=0, error=None):
        with self._lock:
            prefix = {"component": "component", "prewarm": "prewarm", "fallback": "fallback"}[event]
            self._values[f"{prefix}_attempts"] += 1
            outcome = "successes" if success else "failures"
            self._values[f"{prefix}_{outcome}"] += 1
            if event == "component":
                self._values["component_duration_ms"] += max(0, int(duration_ms))
            self._values.update(
                last_event=event,
                last_engine=engine,
                last_error_type=(getattr(error, "error_type", None) or type(error).__name__) if error is not None else None,
                last_event_at=time.time(),
            )

    def component(self, engine, *, success, duration_ms, error=None):
        self._record("component", engine, success=success, duration_ms=duration_ms, error=error)

    def prewarm(self, engine, *, success, duration_ms, error=None):
        self._record("prewarm", engine, success=success, duration_ms=duration_ms, error=error)

    def fallback(self, engine, *, success, error=None):
        self._record("fallback", engine, success=success, error=error)

    def snapshot(self):
        with self._lock:
            result = dict(self._values)
        attempts = result["component_attempts"]
        result["component_success_rate"] = (
            round(result["component_successes"] / attempts, 4) if attempts else None
        )
        return result


class ComponentOcrEngineRunner:
    """Translate one Host engine attempt into the public component contract."""

    def __init__(self, service_factory=None, request_factory=None, metrics=None):
        self._service_factory = service_factory or _default_service_factory
        self._request_factory = request_factory or _default_request_factory
        self._metrics = metrics or OcrRuntimeMetrics()
        self._service_lock = threading.Lock()
        self._service = None

    def _service_for(self, job=None):
        with self._service_lock:
            if self._service is None:
                self._service = self._service_factory(job)
            return self._service

    def __call__(self, *, ctx, image_dir, recog_path, engine, job=None):
        started = time.perf_counter()
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
        try:
            self._service_for(job).recognize_exact(request)
            if not Path(recog_path).is_file():
                raise RuntimeError("component OCR produced no output")
            if job is not None:
                job.check_cancelled()
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000)
            self._metrics.component(engine, success=False, duration_ms=duration_ms, error=exc)
            _LOG.warning(
                "ocr_component_attempt outcome=failure engine=%s duration_ms=%s error_type=%s",
                engine, duration_ms, type(exc).__name__,
            )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000)
        self._metrics.component(engine, success=True, duration_ms=duration_ms)
        _LOG.info(
            "ocr_component_attempt outcome=success engine=%s duration_ms=%s",
            engine, duration_ms,
        )
        return True

    def prewarm(self, engine: str) -> bool:
        started = time.perf_counter()
        try:
            ok = bool(self._service_for().prewarm(engine).ok)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000)
            self._metrics.prewarm(engine, success=False, duration_ms=duration_ms, error=exc)
            _LOG.warning(
                "ocr_component_prewarm outcome=failure engine=%s duration_ms=%s error_type=%s",
                engine, duration_ms, type(exc).__name__,
            )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000)
        error = None if ok else RuntimeError("component prewarm rejected")
        self._metrics.prewarm(
            engine, success=ok, duration_ms=duration_ms, error=error
        )
        _LOG.info(
            "ocr_component_prewarm outcome=%s engine=%s duration_ms=%s",
            "success" if ok else "failure", engine, duration_ms,
        )
        return ok

    def record_fallback(self, *, engine, success, error=None):
        self._metrics.fallback(engine, success=success, error=error)
        _LOG.log(
            logging.INFO if success else logging.ERROR,
            "ocr_component_fallback outcome=%s engine=%s error_type=%s",
            "success" if success else "failure",
            engine,
            type(error).__name__ if error is not None else "none",
        )

    def status(self):
        with self._service_lock:
            service = self._service
        worker = getattr(service, "_worker", None)
        try:
            worker_alive = bool(worker and worker.alive())
        except Exception:
            worker_alive = False
        metrics = self._metrics.snapshot()
        return {
            "metrics": metrics,
            "worker": {
                "created": worker is not None,
                "alive": worker_alive,
                "pid": getattr(worker, "pid", None) if worker is not None else None,
            },
            "retry_count": int(getattr(service, "_submit_rebuilds", 0) or 0),
            "one_shot_fallback": bool(metrics.get("fallback_attempts")),
            "last_error_type": metrics.get("last_error_type"),
        }
    def shutdown(self) -> None:
        with self._service_lock:
            service, self._service = self._service, None
        if service is not None:
            service.shutdown()
