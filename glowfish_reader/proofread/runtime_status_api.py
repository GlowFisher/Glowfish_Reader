"""Read-only runtime diagnostics assembled by the V2 composition root."""

from __future__ import annotations

import threading

from fastapi import APIRouter


router = APIRouter()
_LOCK = threading.Lock()
_PROVIDER = lambda: {"ocr": {"mode": "legacy", "policy": "legacy"}}


def configure_runtime_status_provider(provider):
    global _PROVIDER
    if not callable(provider):
        raise TypeError("runtime status provider must be callable")
    with _LOCK:
        previous, _PROVIDER = _PROVIDER, provider
    return previous


@router.get("/api/runtime/status")
def runtime_status():
    with _LOCK:
        provider = _PROVIDER
    return provider()
