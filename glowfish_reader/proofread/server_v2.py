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
import ui_assets
import update_api


(appconfig.data_root() / "users").mkdir(parents=True, exist_ok=True)

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
        shutdown_hooks=(content_api.shutdown_ocr,),
    )
)


if __name__ == "__main__":
    from launcher import serve

    serve(app, appconfig)
