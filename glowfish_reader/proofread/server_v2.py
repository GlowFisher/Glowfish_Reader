"""V2 production composition entry point.

Legacy routers remain injected while their implementations migrate behind public
component ports. The old ``server.py`` stays available as an explicit rollback
entry during this transition.
"""

from glowfish_host import AppComponents, create_app

import appconfig
import auth_api
import capabilities_api
import content_api
import export_api
import library_api
import notice_api
import ocr_component_runtime
import ui_assets
import update_api


(appconfig.data_root() / "users").mkdir(parents=True, exist_ok=True)


def _configure_ocr_runtime():
    if ocr_component_runtime.component_runtime_enabled():
        runner = ocr_component_runtime.ComponentOcrEngineRunner()
        content_api.configure_ocr_engine_runner(runner)
        return runner
    content_api.configure_ocr_engine_runner(None)
    return None


OCR_RUNNER = _configure_ocr_runtime()
OCR_RUNTIME = "component" if OCR_RUNNER is not None else "legacy"


def _shutdown_component_ocr():
    if OCR_RUNNER is not None:
        OCR_RUNNER.shutdown()


app = create_app(
    AppComponents(
        routers=(
            auth_api.router,
            update_api.router,
            notice_api.router,
            capabilities_api.router,
            content_api.router,
            export_api.router,
            library_api.router,
        ),
        ui_dist=ui_assets.ui_dist(),
        shutdown_hooks=(
            _shutdown_component_ocr,
            content_api.shutdown_ocr,
        ),
    )
)


if __name__ == "__main__":
    from launcher import serve

    serve(app, appconfig)
