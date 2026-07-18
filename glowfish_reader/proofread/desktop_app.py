# -*- coding: utf-8 -*-
"""Glowfish Reader 史料阅读器 —— 本地桌面 App 入口（pywebview 原生窗 + 内嵌 FastAPI）。

· 单机模式：无登录、数据落 %APPDATA%\\Glowfish Reader 史料阅读器\\、默认引擎由 appconfig/engines 决定。
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
from _version import __version__

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _restore_frozen_worker_stdio():
    """Bind inherited pipes hidden by PyInstaller's windowed bootloader."""
    if not (
        getattr(sys, "frozen", False)
        and os.name == "nt"
        and "--ocr" in sys.argv
        and "--serve-worker" in sys.argv
    ):
        return

    import ctypes
    import io
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_std_handle = kernel32.GetStdHandle
    get_std_handle.argtypes = [ctypes.c_ulong]
    get_std_handle.restype = ctypes.c_void_p
    invalid = ctypes.c_void_p(-1).value

    def bind(name, handle_id, flags, mode, *, write_through=False):
        if getattr(sys, name) is not None:
            return
        handle = get_std_handle(handle_id)
        if handle in (None, 0, invalid):
            raise RuntimeError(f"inherited {name} pipe is unavailable")
        fd = msvcrt.open_osfhandle(handle, flags)
        raw = os.fdopen(fd, mode, buffering=0)
        stream = io.TextIOWrapper(
            raw, encoding="utf-8", errors="replace", write_through=write_through
        )
        setattr(sys, name, stream)

    bind("stdin", -10, os.O_RDONLY, "rb")
    bind("stdout", -11, os.O_WRONLY, "wb", write_through=True)
    bind("stderr", -12, os.O_WRONLY, "wb", write_through=True)

def _harden_std():
    """windowed(无控制台) exe 双击时 sys.stdout/err 为 None；uvicorn 日志 / 识别脚本 print
    写 None 会崩溃退出。仅在为 None 时兜底到 devnull（有真实句柄则保留，不影响 --serve 回显）。"""
    import io
    if sys.stdout is None:
        sys.stdout = io.TextIOWrapper(open(os.devnull, "wb"), encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = io.TextIOWrapper(open(os.devnull, "wb"), encoding="utf-8")


_restore_frozen_worker_stdio()
_harden_std()


def _configure_runtime_logging(mode):
    """尽早接入持久日志；日志目录异常不得反过来阻断应用启动。"""
    try:
        import runtime_logging
        return runtime_logging.configure_runtime_logging(mode)
    except Exception:
        return None


def _run_ocr_child():
    """打包态识别子进程分发：sys.argv = [exe, '--ocr', <engine>, <recognize 参数...>]。"""
    _configure_runtime_logging("ocr")
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
    from server_v2 import app
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
            import logging
            logging.getLogger("glowfish.prewarm").exception("OCR prewarm failed")
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
        runtime = json.loads(urllib.request.urlopen(base + "/api/runtime/status", timeout=5).read())
        runtime_mode = (runtime.get("ocr") or {}).get("mode")
        ok = (
            me.get("single") is True and caps.get("ok") is True
            and runtime_mode in {"legacy", "component"}
        )
        missing = [c["label"] for c in caps.get("capabilities", {}).values() if not c["ok"]]
        detail = f" missing={missing}" if missing else ""
        print(f"SELFTEST {'OK' if ok else 'FAIL'}: me={me} capabilities_ok={caps.get('ok')} ocr_runtime={runtime_mode}{detail}")
        return 0 if ok else 1
    except Exception as e:
        print(f"SELFTEST FAIL: {e!r}")
        return 1
    finally:
        try:
            server.should_exit = True
        except Exception:
            pass


def _selftest_ocr_deps():
    """使用 PaddleX 自身逻辑验证冻结包里的 OCR 依赖元数据。"""
    try:
        from paddlex.utils import deps
        required = tuple(deps.EXTRAS.get("ocr-core", ()))
        missing = [name for name in required if not deps.is_dep_available(name)]
        if missing:
            print("SELFTEST OCR DEPS FAIL: " + ", ".join(missing))
            return 1
        if not required:
            print("SELFTEST OCR DEPS FAIL: PaddleX declares no ocr-core dependencies")
            return 1
        print("SELFTEST OCR DEPS OK: " + ", ".join(required))
        return 0
    except Exception as exc:
        print(f"SELFTEST OCR DEPS FAIL: {exc!r}")
        return 1


def _selftest_ocr():
    """构建两个出厂 OCR 档位，并对固定图片执行一次离线识别。"""
    import json
    import tempfile
    import recognize_ppocrv6_onnx as ocr

    candidates = (
        HERE / "assets" / "selftest" / "vertical_cht_clean.png",
        HERE.parent / "bench" / "fixtures" / "vertical_cht_clean.png",
    )
    fixture = next((path for path in candidates if path.is_file()), None)
    if fixture is None:
        print("SELFTEST OCR FAIL: fixture missing")
        return 1

    presets = (
        {"text_det_limit_side_len": 960, "text_det_limit_type": "max"},
        {"profile": "high_accuracy"},
    )
    try:
        with tempfile.TemporaryDirectory(prefix="glowfish_ocr_selftest_") as tmp:
            for index, config in enumerate(presets):
                out = Path(tmp) / f"result_{index}.json"
                engine = ocr._build_engine(dict(config))
                pages, failed = ocr.run_job(
                    engine, fixture.parent, out, log=lambda *_args: None, config=config,
                )
                result = json.loads(out.read_text(encoding="utf-8"))
                lines = sum(len(page.get("lines") or ()) for page in result.values())
                if pages != 1 or failed != 0 or lines < 1:
                    raise RuntimeError(
                        f"preset {index} invalid result: pages={pages} failed={failed} lines={lines}"
                    )
        print("SELFTEST OCR OK")
        return 0
    except Exception as exc:
        print(f"SELFTEST OCR FAIL: {exc!r}")
        return 1


def _selftest_ocr_resident():
    """Exercise the frozen resident worker through a Unicode, spaced, long path."""
    import json
    import shutil
    import tempfile
    from types import SimpleNamespace

    component_root = os.environ.get("GLOWFISH_OCR_ROOT")
    candidates = (
        HERE / "assets" / "selftest" / "vertical_cht_clean.png",
        HERE.parent / "bench" / "fixtures" / "vertical_cht_clean.png",
        (
            Path(component_root) / "bench" / "fixtures" / "vertical_cht_clean.png"
            if component_root else None
        ),
    )
    fixture = next(
        (path for path in candidates if path is not None and path.is_file()), None
    )
    if fixture is None:
        print("SELFTEST OCR RESIDENT FAIL: fixture missing")
        return 1

    runner = None
    try:
        with tempfile.TemporaryDirectory(prefix="glowfish_resident_") as tmp:
            root = Path(tmp) / "\u4e2d\u6587 path with spaces" / ("long-path-" * 8)
            image_dir = root / "\u56fe\u7247 input"
            image_dir.mkdir(parents=True)
            shutil.copy2(fixture, image_dir / "\u7e41\u9ad4 sample.png")
            output = root / "\u8bc6\u522b result.json"
            progress = root / "\u8fdb\u5ea6 status.json"

            import ocr_component_runtime

            runner = ocr_component_runtime.ComponentOcrEngineRunner()
            runner(
                ctx=SimpleNamespace(progress_path=progress),
                image_dir=image_dir,
                recog_path=output,
                engine="ppocrv6_onnx",
            )
            result = json.loads(output.read_text(encoding="utf-8"))
            lines = sum(len(page.get("lines") or ()) for page in result.values())
            status = runner.status()
            worker = status.get("worker") or {}
            if lines < 1 or not worker.get("alive") or not worker.get("pid"):
                raise RuntimeError(
                    f"invalid resident result: lines={lines} worker={worker}"
                )
            if status.get("one_shot_fallback") or status.get("retry_count") != 0:
                raise RuntimeError(f"unexpected resident fallback/retry: {status}")
        print("SELFTEST OCR RESIDENT OK")
        return 0
    except Exception as exc:
        print(f"SELFTEST OCR RESIDENT FAIL: {exc!r}")
        return 1
    finally:
        if runner is not None:
            runner.shutdown()

def _selftest_release_fixes():
    """冻结版发布闸：验证附带原图导出与持久运行日志确实进入当前构建。"""
    import io
    import json
    import logging
    import tempfile
    import zipfile
    from docx import Document
    from PIL import Image

    old_data_dir = os.environ.get("SHUPAI_DATA_DIR")
    try:
        with tempfile.TemporaryDirectory(prefix="glowfish_release_fixes_") as tmp:
            root = Path(tmp).resolve()
            os.environ["SHUPAI_DATA_DIR"] = str(root)

            import appconfig
            appconfig.WORK = root
            appconfig.CONFIG_PATH = root / "app_config.json"

            log_path = _configure_runtime_logging("release-selftest")
            logging.getLogger("glowfish.release").error("运行日志发布自检")
            for handler in logging.getLogger().handlers:
                handler.flush()
            if not log_path or "运行日志发布自检" not in Path(log_path).read_text(encoding="utf-8"):
                raise RuntimeError("runtime log marker missing")

            import safefs
            safefs.WORK_ROOT = root
            batch, page_id = "release-fixture", "page1"
            src = root / batch / "_src"
            src.mkdir(parents=True)
            Image.new("RGB", (24, 24), "white").save(src / f"{page_id}.png")
            proof = {
                "batch": batch,
                "image_dir": str(src),
                "pages": [{
                    "page_id": page_id,
                    "image": f"_img/{page_id}.jpg",
                    "lines": [{"id": "l1", "text": "发布自检", "deleted": False, "para_break": True}],
                    "order": ["l1"],
                }],
            }
            proof_path = root / batch / "proof.json"
            proof_path.write_text(json.dumps(proof, ensure_ascii=False), encoding="utf-8")

            class _Ctx:
                def reg(self, name):
                    return {"proof_path": str(proof_path)} if name == batch else None

            from export_api import _export_selected
            body = {"selected": [{"batch": batch, "page_ids": [page_id]}]}
            docx_response = _export_selected(_Ctx(), body, "docx", True)
            if len(Document(io.BytesIO(docx_response.body)).inline_shapes) != 1:
                raise RuntimeError("DOCX source image missing")
            md_response = _export_selected(_Ctx(), body, "md", True)
            with zipfile.ZipFile(io.BytesIO(md_response.body)) as archive:
                if not any(name.endswith("_原图/0001_page1.png") for name in archive.namelist()):
                    raise RuntimeError("ZIP source image missing")

            for handler in list(logging.getLogger().handlers):
                handler.flush()
                handler.close()
                logging.getLogger().removeHandler(handler)
        print("SELFTEST RELEASE FIXES OK")
        return 0
    except Exception as exc:
        print(f"SELFTEST RELEASE FIXES FAIL: {exc!r}")
        return 1
    finally:
        if old_data_dir is None:
            os.environ.pop("SHUPAI_DATA_DIR", None)
        else:
            os.environ["SHUPAI_DATA_DIR"] = old_data_dir

def run():
    """起内嵌服务 + pywebview 原生窗口（阻塞至关窗）。"""
    _configure_runtime_logging("desktop")
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

    win = webview.create_window(f"Glowfish Reader V{__version__}", f"http://{host}:{port}/",
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
        try:
            import content_api
            content_api.shutdown_ocr()
        except Exception:
            pass
        server.should_exit = True               # 关窗后优雅停服
    except Exception:
        pass


def _serve_headless():
    """无界面前台起服务（调试 / 打包 E2E 验证 / 内网共享）：exe --serve [port] [host]。"""
    _configure_runtime_logging("server")
    os.environ.setdefault("SHUPAI_MODE", "single")
    os.environ["SHUPAI_OPEN_BROWSER"] = "0"
    import uvicorn
    from server_v2 import app
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
    if arg1 == "--selftest-ocr-deps":
        sys.exit(_selftest_ocr_deps())
    if arg1 == "--selftest-ocr":
        sys.exit(_selftest_ocr())
    if arg1 == "--selftest-ocr-resident":
        sys.exit(_selftest_ocr_resident())
    if arg1 == "--selftest-release-fixes":
        sys.exit(_selftest_release_fixes())
    if arg1 == "--benchmark-ocr-runtime":
        from ocr_runtime_benchmark import main as benchmark_main
        sys.exit(benchmark_main(sys.argv[2:]))
    if arg1 == "--serve":
        _serve_headless()
        sys.exit(0)
    try:
        run()
    except Exception as e:                       # 启动崩溃：留痕 + 尽力弹原生错误框
        import logging
        logging.getLogger("glowfish.crash").exception("Desktop startup failed")
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
