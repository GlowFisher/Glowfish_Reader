# -*- coding: utf-8 -*-
"""配置中心：集中解析运行参数、数据根目录与 Paddle 解释器路径，消除本机硬编码。

取值优先级（高→低）：
  1) 环境变量 SHUPAI_HOST / SHUPAI_PORT / SHUPAI_OPEN_BROWSER / SHUPAI_ENGINE /
     SHUPAI_PADDLE_PY / SHUPAI_MODE / SHUPAI_DATA_DIR
  2) <数据根>/app_config.json（首次自检写入，可手改）
  3) 自动探测（仅 Paddle 解释器）
  4) 内置默认

数据根目录（data_root）—— 所有用户数据/配置只落这里，绝不触碰其它目录：
  · 开发态（源码直跑）   = proofread/_work/        （沿用旧路径，不打扰在研数据）
  · 打包态（PyInstaller）= %APPDATA%\\Glowfish Reader 史料阅读器\\   （安装版不写程序目录）
  · SHUPAI_DATA_DIR 显式覆盖最高优先。

运行模式（mode）：
  · single = 本机单用户桌面 App（无登录；current_user 直接给本机用户）—— 打包默认
  · multi  = 内网多用户网页版（注册/登录/隔离）—— 机构私有化 SKU 备用，需显式启用
"""
import os
import sys
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_NAME = "Glowfish Reader 史料阅读器"

_BOOL_TRUE = {"1", "true", "yes", "on", "y"}


def is_frozen():
    """是否运行在 PyInstaller 打包产物内（决定数据根落 %APPDATA% 还是源码 _work/）。"""
    return bool(getattr(sys, "frozen", False))


def _read_bundle_sku():
    """打包态读 bundle 内 sku.txt 的构建期 SKU 标记（single/multi）；缺失/异常返回 ''。"""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return ""
    try:
        return (Path(base) / "sku.txt").read_text(encoding="utf-8").strip().lower()
    except Exception:
        return ""


def _resolve_data_root():
    """解析数据根：SHUPAI_DATA_DIR > (打包态 %APPDATA%/应用名) > 源码 _work/。"""
    ev = os.environ.get("SHUPAI_DATA_DIR")
    if ev:
        return Path(ev)
    if is_frozen():
        base = os.environ.get("APPDATA") or str(Path.home())
        new_path = Path(base) / APP_NAME
        # 迁移旧路径：v1 的数据落在「GlowFish史料阅读器」
        old_path = Path(base) / "GlowFish史料阅读器"
        if old_path.exists() and not new_path.exists():
            return old_path
        return new_path
    return HERE / "_work"


# 数据根：进程内固定（仅取决于 env/打包态，与配置文件无关，故可在导入期定下，无循环依赖）
WORK = _resolve_data_root()
CONFIG_PATH = WORK / "app_config.json"


def data_root():
    """当前进程的数据根目录（Path）。safefs / userctx / auth 等统一据此定位。"""
    return WORK

DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8741,
    "open_browser": True,
    "engine": "ppocrv6",  # 默认官方 PP-OCRv6；onnx 经 SHUPAI_ENGINE 可切回 + 自动兜底
    "paddle_py": None,   # None=运行时自动探测
}


def _load_file():
    if CONFIG_PATH.exists():
        try:
            d = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {}


def _save_file(d):
    try:
        WORK.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _env(name):
    v = os.environ.get(name)
    return v if v not in (None, "") else None


def _as_bool(v, default):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in _BOOL_TRUE


def _as_int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ---- Paddle 解释器自动探测 ----
def _env_python(env_dir):
    """conda env 目录 → 其 python 解释器路径（存在才返回）。"""
    cand = env_dir / "python.exe" if os.name == "nt" else env_dir / "bin" / "python"
    return str(cand) if cand.is_file() else None


def detect_paddle_python():
    """按优先级返回 paddleocr env 的 python 路径；找不到返回 None（不抛）。"""
    ev = _env("SHUPAI_PADDLE_PY")               # 1) 环境变量
    if ev and Path(ev).is_file():
        return ev
    fv = _load_file().get("paddle_py")          # 2) 配置文件
    if fv and Path(fv).is_file():
        return fv
    home = Path.home()                          # 3) 扫常见 conda envs，精确匹配名含 paddle
    for base in (home / "miniconda3" / "envs", home / "anaconda3" / "envs"):
        if not base.is_dir():
            continue
        for env_dir in sorted(base.iterdir()):
            if env_dir.is_dir() and "paddle" in env_dir.name.lower():
                p = _env_python(env_dir)
                if p:
                    return p
    conda = shutil.which("conda")               # 4) conda env list 兜底
    if conda:
        try:
            r = subprocess.run([conda, "env", "list"], capture_output=True,
                               text=True, timeout=20)
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if "paddle" in parts[0].lower():
                    p = _env_python(Path(parts[-1]))
                    if p:
                        return p
        except Exception:
            pass
    return None


def get_paddle_python():
    """探测 Paddle 解释器；命中后回写配置（便于手改）。找不到返回 None。"""
    p = detect_paddle_python()
    if p:
        d = _load_file()
        if d.get("paddle_py") != p:
            d["paddle_py"] = p
            _save_file(d)
    return p


def get_host():
    return _env("SHUPAI_HOST") or _load_file().get("host") or DEFAULTS["host"]


def get_port():
    v = _env("SHUPAI_PORT")
    if v is None:
        v = _load_file().get("port")
    return _as_int(v, DEFAULTS["port"])


def get_engine():
    return _env("SHUPAI_ENGINE") or _load_file().get("engine") or DEFAULTS["engine"]


def should_open_browser():
    ev = _env("SHUPAI_OPEN_BROWSER")
    if ev is not None:
        return _as_bool(ev, True)
    fv = _load_file().get("open_browser")
    if fv is not None:
        return bool(fv)
    return DEFAULTS["open_browser"]


def get_account_entitlement():
    """Return account entitlement display config for the account menu."""
    mode = (_env("SHUPAI_ACCOUNT_MODE") or _load_file().get("account_mode") or "trial").strip().lower()
    expires_at = (_env("SHUPAI_ACCOUNT_EXPIRES_AT") or _load_file().get("account_expires_at") or "2026-08-31").strip()
    if mode not in ("trial", "member") or not expires_at:
        return None
    return {"mode": mode, "expires_at": expires_at}

def get_mode():
    """运行模式 single/multi。
    · 打包态：锁定为 bundle 内 sku.txt（消费版 single / 机构版 multi），**忽略 SHUPAI_MODE
      环境变量**——授权门不可经环境变量绕过；无标记默认 single。
    · 开发态：固定 single；登录/注册仅保留给打包态 multi SKU。"""
    if is_frozen():
        sku = _read_bundle_sku()
        return sku if sku in ("single", "multi") else "single"
    return "single"


def is_single():
    return get_mode() == "single"
