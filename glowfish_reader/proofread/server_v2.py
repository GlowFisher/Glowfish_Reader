"""V2 production composition entry point.

Legacy routers remain injected while their implementations migrate behind public
component ports. The old ``server.py`` stays available as an explicit rollback
entry during this transition.
"""

import logging

from glowfish_host import AppComponents, create_app

import appconfig
import auth_api
import capabilities_api
import content_api
import export_api
import library_api
import notice_api
import ocr_component_runtime
import runtime_status_api
import ui_assets
import update_api


(appconfig.data_root() / "users").mkdir(parents=True, exist_ok=True)
_LOG = logging.getLogger("glowfish.ocr.runtime")


def _configure_ocr_runtime():
    policy = ocr_component_runtime.component_runtime_mode()
    if policy == "component":
        runner = ocr_component_runtime.ComponentOcrEngineRunner()
        content_api.configure_ocr_engine_runner(runner)
        return policy, runner
    content_api.configure_ocr_engine_runner(None)
    return policy, None


OCR_POLICY, OCR_RUNNER = _configure_ocr_runtime()
OCR_RUNTIME = "component" if OCR_RUNNER is not None else "legacy"
_LOG.info("ocr_runtime_selected policy=%s effective=%s", OCR_POLICY, OCR_RUNTIME)


def _shutdown_component_ocr():
    if OCR_RUNNER is not None:
        OCR_RUNNER.shutdown()


def _runtime_status():
    ocr = {
        "policy": OCR_POLICY,
        "mode": OCR_RUNTIME,
        "rollback": "set GLOWFISH_OCR_COMPONENT_RUNTIME=legacy and restart",
    }
    if OCR_RUNNER is not None:
        ocr.update(OCR_RUNNER.status())
    else:
        ocr.update(
            metrics=ocr_component_runtime.OcrRuntimeMetrics().snapshot(),
            worker={"created": False, "alive": False, "pid": None},
        )
    return {"ocr": ocr}


runtime_status_api.configure_runtime_status_provider(_runtime_status)


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
            runtime_status_api.router,
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
