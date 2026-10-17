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
    # 开源后已移除登录鉴权（本地单用户）。绑定非回环地址会把史料暴露给局域网任意主机，
    # 这里强制告警，引导用户仅在明确需要内网共享时使用，且需自行承担数据暴露风险。
    if host not in ("127.0.0.1", "localhost", "::1"):
        import logging
        logging.getLogger("glowfish.security").warning(
            "正在绑定非回环地址 %s——已移除登录鉴权，史料数据将对局域网暴露，请确认此行为符合预期。", host
        )
    url = f"http://{host}:{port}/"
    if config.should_open_browser():
        threading.Thread(target=lambda: (time.sleep(2), _open_browser(url)), daemon=True).start()
    uvicorn.run(app, host=host, port=port)
