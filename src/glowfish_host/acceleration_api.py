"""Injectable FastAPI routes for optional GPU acceleration."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .acceleration import GpuRuntimeManager


def create_acceleration_router(manager: GpuRuntimeManager, *, get_preference, set_preference) -> APIRouter:
    router = APIRouter()

    @router.get("/api/ocr/acceleration")
    def acceleration_status():
        return manager.status(preference=get_preference())

    @router.post("/api/ocr/acceleration/install")
    def install_acceleration():
        # A release integration replaces this guarded response with its signed
        # manifest downloader.  Never download without a pinned manifest.
        manager.mark_failure("runtime_manifest_unavailable")
        return manager.status(preference=get_preference())

    @router.get("/api/ocr/acceleration/install/status")
    def install_status():
        return manager.status(preference=get_preference())

    @router.post("/api/ocr/acceleration/enable")
    def enable_acceleration():
        status = manager.status(preference=get_preference())
        if status["state"] != "ready":
            raise HTTPException(status_code=409, detail=status["reason_code"] or "runtime_not_ready")
        set_preference("auto")
        return manager.status(preference="auto")

    @router.post("/api/ocr/acceleration/disable")
    def disable_acceleration():
        set_preference("cpu")
        return manager.status(preference="cpu")

    @router.delete("/api/ocr/acceleration")
    def uninstall_acceleration():
        set_preference("cpu")
        manager.uninstall()
        return manager.status(preference="cpu")

    return router
