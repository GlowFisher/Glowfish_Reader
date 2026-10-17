from pathlib import Path

from fastapi import APIRouter
from fastapi.testclient import TestClient

from glowfish_host import AppComponents, create_app


def test_composition_injects_routes_ui_health_and_shutdown(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("host-ui", encoding="utf-8")
    (ui / "manifest.json").write_text('{"schema_version": 1}', encoding="utf-8")

    router = APIRouter()

    @router.get("/api/probe")
    def probe():
        return {"component": "router"}

    stopped = []
    app = create_app(
        AppComponents(
            routers=(router,),
            ui_dist=ui,
            shutdown_hooks=(lambda: stopped.append(True),),
        )
    )

    with TestClient(app) as client:
        assert client.get("/health").json() == {"ok": True}
        assert client.get("/api/probe").json() == {"component": "router"}
        assert client.get("/").text == "host-ui"

    assert stopped == [True]


def test_desktop_runtime_uses_v2_composition_entry():
    root = Path(__file__).resolve().parents[1]
    desktop = (root / "glowfish_reader" / "proofread" / "desktop_app.py").read_text(encoding="utf-8")
    production_imports = [line.strip() for line in desktop.splitlines() if "from server" in line]
    assert production_imports
    assert 'base + "/api/runtime/status"' in desktop
    assert set(production_imports) == {"from server_v2 import app"}


def test_v2_entry_injects_legacy_routers_without_owning_them():
    root = Path(__file__).resolve().parents[1]
    entry = (root / "glowfish_reader" / "proofread" / "server_v2.py").read_text(encoding="utf-8")
    assert "from glowfish_host import AppComponents, create_app" in entry
    assert "FastAPI(" not in entry
    assert "StaticFiles" not in entry
    assert "ui_dist=ui_assets.ui_dist()" in entry
    assert "_shutdown_component_ocr" in entry
    assert "content_api.shutdown_ocr" in entry
    assert "ocr_component_runtime.component_runtime_mode()" in entry
    assert "runtime_status_api.configure_runtime_status_provider" in entry
    assert "runtime_status_api.router" in entry
    assert "OCR_POLICY, OCR_RUNNER = _configure_ocr_runtime()" in entry
    assert "ocr_component_runtime.ComponentOcrEngineRunner(" in entry
    assert 'OCR_RUNTIME = "component" if OCR_RUNNER is not None else "legacy"' in entry
    assert "content_api.configure_ocr_engine_runner(None)" in entry
