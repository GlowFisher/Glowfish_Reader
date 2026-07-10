# -*- coding: utf-8 -*-
"""GlowFish 史料阅读器 —— 本地桌面 App 入口（pywebview 原生窗 + 内嵌 FastAPI）。

· 单机模式：无登录、数据落 %APPDATA%\\GlowFish史料阅读器\\、默认引擎由 appconfig/engines 决定。
· 随机空闲端口起 uvicorn（仅 127.0.0.1 回环），pywebview 用系统 WebView2 加载，关窗即退。
· 打包态（PyInstaller）下本 exe 兼作识别子进程：`exe --ocr <engine> --images ...`
  经下方分发器跳到识别脚本 main()，规避 sys.executable 非 python 解释器、当脚本跑会重启 GUI 的坑。

用法：
  python desktop_app.py               # 起桌面窗口
  exe --ocr <engine> ...              # 识别子进程（打包态内部用）
  exe --selftest                      # 无界面自检（首启自检/打包冒烟），打印 SELFTEST OK/FAIL
  exe --selftest-capabilities         # 资产自检（模型/词表是否随包），缺件非零退出
打包：见 glowfish_reader.spec
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _harden_std():
    """windowed(无控制台) exe 双击时 sys.stdout/err 为 None；uvicorn 日志 / 识别脚本 print
    写 None 会崩溃退出。仅在为 None 时兜底到 devnull（有真实句柄则保留，不影响 --serve 回显）。"""
    import io
    if sys.stdout is None:
        sys.stdout = io.TextIOWrapper(open(os.devnull, "wb"), encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = io.TextIOWrapper(open(os.devnull, "wb"), encoding="utf-8")


_harden_std()


def _run_ocr_child():
    """打包态识别子进程分发：sys.argv = [exe, '--ocr', <engine>, <recognize 参数...>]。"""
    engine = sys.argv[2] if len(sys.argv) > 2 else "ppocrv6_onnx"
    sys.argv = [sys.argv[0]] + sys.argv[3:]      # 还原成 recognize_xxx.py 期望的 argv
    if engine == "paddle":
        import recognize
        recognize.main()
    elif engine == "ppocrv6":
        import recognize_ppocrv6
        recognize_ppocrv6.main()
    elif engine in {"ppocrv6_onnx", "ppocrv6_onnx_high"}:
        import recognize_ppocrv6_onnx
        recognize_ppocrv6_onnx.main()
    else:
        import recognize_ppocrv6_onnx
        recognize_ppocrv6_onnx.main()
    sys.exit(0)


# 子进程分发须在任何重型 import 之前完成
if len(sys.argv) > 1 and sys.argv[1] == "--ocr":
    _run_ocr_child()


def _free_port():
    """要一个 127.0.0.1 上的空闲端口（绑 0 让内核分配）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_until_up(host, port, timeout=40.0):
    """轮询直到本地服务可连（首启要等 fastapi/onnxruntime 等 import 完）。"""
    import time
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def _start_server():
    """单机模式起内嵌 FastAPI 于随机空闲端口，返回 (server, host, port)。"""
    os.environ.setdefault("SHUPAI_MODE", "single")
    os.environ["SHUPAI_OPEN_BROWSER"] = "0"
    import threading
    import uvicorn
    from server import app
    host, port = "127.0.0.1", _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    return server, host, port


def _prewarm_enabled():
    return os.environ.get("SHUPAI_PREWARM_OCR", "1").strip().lower() not in {"0", "false", "no", "off"}


def _prewarm_async():
    """后台预热常驻 OCR 模型；开发态可用 SHUPAI_PREWARM_OCR=0 跳过。"""
    if not _prewarm_enabled():
        print("PREWARM skipped (SHUPAI_PREWARM_OCR=0)")
        return
    import threading

    def _go():
        try:
            import content_api
            content_api.prewarm()
        except Exception:
            pass
    threading.Thread(target=_go, daemon=True).start()


def _selftest():
    """无界面自检（首启自检 / 打包冒烟）：起服务→探活→打 /api/me、/api/capabilities→退。

    临时数据根，绝不污染用户数据。打印 SELFTEST OK/FAIL，退出码 0/1。
    注：原先打的 /api/license/status 随激活码机制退役已删除（license_api 现无路由），
    改打同样未设门的 /api/capabilities——顺带确认模型/词表随包到位。
    指向不可达授权服务器，避免自检联网拖慢。
    """
    import json
    import tempfile
    import urllib.request
    os.environ["SHUPAI_DATA_DIR"] = tempfile.mkdtemp(prefix="shupai_selftest_")
    os.environ["SHUPAI_LICENSE_SERVER"] = "http://127.0.0.1:1"
    server, host, port = _start_server()
    if not _wait_until_up(host, port):
        print("SELFTEST FAIL: 服务未在限时内就绪")
        return 1
    base = f"http://{host}:{port}"
    try:
        me = json.loads(urllib.request.urlopen(base + "/api/me", timeout=5).read())
        caps = json.loads(urllib.request.urlopen(base + "/api/capabilities", timeout=8).read())
        ok = me.get("single") is True and caps.get("ok") is True
        missing = [c["label"] for c in caps.get("capabilities", {}).values() if not c["ok"]]
        detail = f" missing={missing}" if missing else ""
        print(f"SELFTEST {'OK' if ok else 'FAIL'}: me={me} capabilities_ok={caps.get('ok')}{detail}")
        return 0 if ok else 1
    except Exception as e:
        print(f"SELFTEST FAIL: {e!r}")
        return 1
    finally:
        try:
            server.should_exit = True
        except Exception:
            pass


def run():
    """起内嵌服务 + pywebview 原生窗口（阻塞至关窗）。"""
    server, host, port = _start_server()
    _prewarm_async()                             # 开机即热模型，与等服务/选文件重叠 → 首页识别即时
    import webview
    if not _wait_until_up(host, port):
        webview.create_window(
            "启动失败", html="<h2 style='font-family:Microsoft YaHei,微软雅黑,system-ui,sans-serif;padding:24px'>"
            "本地服务启动失败，请重启应用或联系支持。</h2>")
        webview.start()
        return
    class _Api:
        """暴露给前端 JS 的原生桥（仅桌面壳可用；纯网页态前端探测不到 window.pywebview 自动降级）。"""

        def save_export(self, default_name, b64, start_dir=""):
            """前端拿到导出字节(base64) → 弹系统原生保存对话框 → 写盘。
            返回 {ok, path, dir} / {canceled:True} / {ok:False, error}。"""
            import base64
            try:
                w0 = webview.windows[0] if webview.windows else None
                if w0 is None:
                    return {"ok": False, "error": "窗口未就绪"}
                kw = {"save_filename": default_name or "导出"}
                if start_dir and os.path.isdir(start_dir):   # 记忆目录可能已被删/换盘 → 校验存在再用，否则回默认位置
                    kw["directory"] = start_dir
                res = w0.create_file_dialog(webview.SAVE_DIALOG, **kw)
                path = res[0] if isinstance(res, (list, tuple)) else res
                if not path:
                    return {"canceled": True}
                with open(path, "wb") as f:
                    f.write(base64.b64decode(b64))
                return {"ok": True, "path": str(path), "dir": str(Path(path).parent)}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        def open_folder(self, path):
            """在系统资源管理器里打开文件所在文件夹（Windows os.startfile）。"""
            try:
                folder = path if Path(path).is_dir() else str(Path(path).parent)
                os.startfile(folder)
                return True
            except Exception:
                return False

    win = webview.create_window("Glowfish_Reader 史料阅读器", f"http://{host}:{port}/",
                                width=1280, height=860, min_size=(960, 640), js_api=_Api())

    def _shutdown_for_update():
        """更新 apply 调用：销毁窗口解除 webview.start() 阻塞 → 下方优雅停服 → 进程退出，
        让已 Popen 拉起的安装器就地覆盖并重启。从服务线程调用，失败静默。"""
        try:
            win.destroy()
        except Exception:
            pass
    try:
        import update_api
        update_api.register_shutdown(_shutdown_for_update)
    except Exception:
        pass

    import appconfig
    webview_storage = appconfig.data_root() / "webview_data"
    webview_storage.mkdir(parents=True, exist_ok=True)
    # private_mode 默认 True（pywebview 隐式无痕模式）：localStorage 每次开窗都清零，
    # 公告"已弹过一次"等前端本地状态形同虚设。落到持久数据目录下才能跨次启动保留。
    webview.start(private_mode=False, storage_path=str(webview_storage))
    try:
        server.should_exit = True               # 关窗后优雅停服
    except Exception:
        pass


def _serve_headless():
    """无界面前台起服务（调试 / 打包 E2E 验证 / 内网共享）：exe --serve [port] [host]。"""
    os.environ.setdefault("SHUPAI_MODE", "single")
    os.environ["SHUPAI_OPEN_BROWSER"] = "0"
    import uvicorn
    from server import app
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8799
    host = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1"
    print(f"SERVE http://{host}:{port}/")
    _prewarm_async()
    uvicorn.run(app, host=host, port=port, log_level="warning")


def _log_crash(exc):
    """把启动异常写到数据根 last_error.log（windowed 下无控制台，否则报错无处可寻）。"""
    try:
        import traceback
        import appconfig
        d = appconfig.data_root()
        d.mkdir(parents=True, exist_ok=True)
        (d / "last_error.log").write_text(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    arg1 = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg1 == "--selftest":
        sys.exit(_selftest())
    if arg1 == "--selftest-capabilities":
        import capabilities
        sys.exit(capabilities.selftest())
    if arg1 == "--serve":
        _serve_headless()
        sys.exit(0)
    try:
        run()
    except Exception as e:                       # 启动崩溃：留痕 + 尽力弹原生错误框
        _log_crash(e)
        try:
            import webview
            webview.create_window(
                "启动失败", html="<h2 style='font-family:Microsoft YaHei,微软雅黑,system-ui,sans-serif;padding:24px'>"
                "应用启动失败，详情见数据目录 last_error.log。</h2>")
            webview.start()
        except Exception:
            pass
        sys.exit(1)
