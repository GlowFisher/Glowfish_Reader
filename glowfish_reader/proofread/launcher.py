from __future__ import annotations

import os
import shutil
import subprocess


def _chrome_path():
    if os.name != "nt":
        return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chrome")
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    return next((item for item in candidates if os.path.isfile(item)), None)


def _open_browser(url: str) -> None:
    try:
        chrome = _chrome_path()
        if chrome:
            subprocess.Popen([chrome, url])
            return
    except Exception:
        pass
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


def serve(app, config) -> None:
    import threading
    import time
    import uvicorn

    host, port = config.get_host(), config.get_port()
    url = f"http://{host}:{port}/"
    if config.should_open_browser():
        threading.Thread(target=lambda: (time.sleep(2), _open_browser(url)), daemon=True).start()
    uvicorn.run(app, host=host, port=port)
