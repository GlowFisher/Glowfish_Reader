from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles


@dataclass(frozen=True)
class AppComponents:
    routers: Iterable[APIRouter]
    ui_dist: Path
    startup_hooks: Iterable[Callable[[], None]] = field(default_factory=tuple)
    shutdown_hooks: Iterable[Callable[[], None]] = field(default_factory=tuple)


def create_app(components: AppComponents) -> FastAPI:
    """Create the local HTTP app; all behavior arrives through injected components."""
    ui_dist = Path(components.ui_dist).resolve()
    manifest = ui_dist / "manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError(f"built UI manifest missing: {manifest}")

    app = FastAPI(title="Glowfish Reader")

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    for hook in components.startup_hooks:
        app.router.add_event_handler("startup", hook)
    for hook in components.shutdown_hooks:
        app.router.add_event_handler("shutdown", hook)
    for router in components.routers:
        app.include_router(router)
    app.mount("/", StaticFiles(directory=str(ui_dist), html=True), name="ui")
    return app
