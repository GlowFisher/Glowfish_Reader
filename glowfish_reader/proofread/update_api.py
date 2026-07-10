# -*- coding: utf-8 -*-
"""应用更新本地接口层（挂进 server.py，不设授权门——授权过期也要能升级到修复版）。

端点：
  GET  /api/update/check     → 检查更新决策（current/has_update/mandatory/latest/notes/...）
  POST /api/update/download  → 后台线程下载新安装包（幂等，已在下则忽略）
  GET  /api/update/progress  → 下载进度状态机（idle/downloading/ready/error）
  POST /api/update/apply     → 校验就绪后拉起安装器并关窗退出（仅就绪态才动作）

下载/拉起的真伪与平台行为见 updater.py；本层只做编排 + 进度状态 + 关窗钩子。
"""
import threading

from fastapi import APIRouter

import appconfig
import updater

router = APIRouter()

# 下载进度状态机（单机桌面，单一全局状态，加锁线程安全）
_lock = threading.Lock()
_IDLE = {"phase": "idle", "done": 0, "total": 0, "file": None, "error": None}
_state = dict(_IDLE)

# 关窗钩子：桌面壳启动时 register_shutdown(销毁窗口+停服)；web 模式不注册（无窗，apply 不可达）
_shutdown_hook = None


def _reset():
    """测试用：状态归零。"""
    global _state
    with _lock:
        _state = dict(_IDLE)


def _set(**kw):
    with _lock:
        _state.update(kw)


def read_progress() -> dict:
    with _lock:
        return dict(_state)



def _download_dir():
    """安装包下载目录（数据根下 _update/，与程序目录/用户史料隔离）。"""
    return appconfig.data_root() / "_update"



def check_status() -> dict:
    """据本机版本 + 远端清单给出更新决策，附 current 字段。联网失败软返回 has_update False。
"""
    cur = updater.current_version()
    manifest = updater.fetch_manifest(updater.manifest_url())
    info = updater.evaluate(cur, manifest)
    info["current"] = cur
    return info


def _do_download(info: dict):
    """同步执行一次下载 + 校验，驱动进度状态机（由 start_download 放到后台线程跑）。"""
    try:
        _set(phase="downloading", done=0, total=info.get("size", 0), file=None, error=None)
        dest = _download_dir() / f"glowfish_reader_setup_{info.get('latest', 'new')}.exe"
        updater.download(info["url"], dest,
                         progress_cb=lambda d, t: _set(done=d, total=t or info.get("size", 0)))
        if not updater.verify_sha256(dest, info.get("sha256", "")):
            _set(phase="error", error="sha256_mismatch")
            return
        _set(phase="ready", file=str(dest))
    except Exception as e:                       # 网络/磁盘异常软落 error，前端可提示重试
        _set(phase="error", error=str(e) or "download_failed")


def start_download(info: dict):
    """启动后台下载（已在下载中则忽略，幂等）。"""
    with _lock:
        if _state["phase"] == "downloading":
            return
    threading.Thread(target=_do_download, args=(info,), daemon=True).start()



def register_shutdown(fn):
    """桌面壳注册关窗+停服回调，供 apply 在拉起安装器后调用。"""
    global _shutdown_hook
    _shutdown_hook = fn


def _request_shutdown():
    if _shutdown_hook:
        _shutdown_hook()


@router.get("/api/update/check")
def api_check():
    return check_status()


@router.post("/api/update/download")
def api_download():
    info = check_status()
    if not info.get("has_update"):
        return {"ok": False, "reason": "no_update"}
    start_download(info)
    return {"ok": True}


@router.get("/api/update/progress")
def api_progress():
    return read_progress()


@router.post("/api/update/apply")
def api_apply():
    st = read_progress()
    if st.get("phase") != "ready" or not st.get("file"):
        return {"ok": False, "reason": "not_ready"}
    updater.launch_installer(st["file"])         # 应用内下载无 MotW → 不触发 SmartScreen
    _request_shutdown()                          # 关窗停服，让安装器就地覆盖后重启
    return {"ok": True}
