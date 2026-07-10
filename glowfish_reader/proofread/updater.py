# -*- coding: utf-8 -*-
"""应用更新客户端逻辑（纯本地决策 + 下载/校验/拉起安装器）。

设计（详见方案）：不做进程内自替换（onedir 包大、运行中 exe 被占用），而是
「拉远端 update.json → 应用内下载新安装包 → sha256 校验 → Popen 拉起 Inno 安装器
就地升级（同 AppId 自动升级，用户数据在 %APPDATA% 不碰）→ 自动重启」。

完整性用 sha256 + HTTPS 替代代码签名；应用自行下载的安装包不带 MotW，
Popen 拉起不触发 SmartScreen（个人运营、无签名也几乎无摩擦）。

联网一律短超时、软失败（仿 licensing/client）：拉不到清单返回 None，绝不抛给上层。
"""
import os
import re
import hashlib
import subprocess
from pathlib import Path

import requests

import _version

_DEF_TIMEOUT = 6
_CHUNK = 256 * 1024
_DEFAULT_SERVER = "https://license.glowfishreader.com"


def current_version() -> str:
    """本机运行版本（单一真源 _version.__version__）。"""
    return _version.__version__


def manifest_url() -> str:
    """更新清单 update.json 的地址。

    优先级：SHUPAI_UPDATE_URL（整条覆盖，便于测试）> 由 SHUPAI_LICENSE_SERVER 推导
    （与授权服务器同源 https）> 内置默认 license.glowfishreader.com。
    """
    u = os.environ.get("SHUPAI_UPDATE_URL")
    if u:
        return u
    base = os.environ.get("SHUPAI_LICENSE_SERVER") or _DEFAULT_SERVER
    return base.rstrip("/") + "/update.json"


def parse_version(s) -> tuple:
    """'1.2.3' / ' v1.0.0 ' → (1,2,3)。容错：取前三段数字，缺位补 0。"""
    nums = re.findall(r"\d+", str(s or ""))
    nums = [int(x) for x in nums[:3]]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def is_newer(candidate, base) -> bool:
    """candidate 版本是否数字意义上比 base 新（1.10.0 > 1.9.0）。"""
    return parse_version(candidate) > parse_version(base)


def evaluate(current, manifest) -> dict:
    """据本机版本与远端清单给出更新决策。

    返回 {"has_update": bool, ...}；有更新时附 mandatory/latest/notes/url/sha256/size。
    mandatory = 清单显式 mandatory，或本机版本低于 min_supported（如轮换服务器密钥后旧版必升）。
    清单 v2：顶层 url/sha256/size 仍指全量安装包（老客户端兼容）；另有 "code" 子对象指
    「代码小包」——新客户端优先取之。
    """
    if not manifest or not manifest.get("latest"):
        return {"has_update": False}
    latest = manifest["latest"]
    if not is_newer(latest, current):
        return {"has_update": False}
    mandatory = bool(manifest.get("mandatory")) or (
        bool(manifest.get("min_supported")) and is_newer(manifest["min_supported"], current))
    code = manifest.get("code")
    pkg = code if isinstance(code, dict) and code.get("url") and code.get("sha256") else manifest
    return {
        "has_update": True,
        "mandatory": mandatory,
        "latest": latest,
        "notes": manifest.get("notes", ""),
        "url": pkg.get("url", ""),
        "sha256": pkg.get("sha256", ""),
        "size": pkg.get("size", 0),
    }




def verify_sha256(path, expected_hex) -> bool:
    """逐块算文件 sha256 与期望值比对（大小写不敏感）。空期望值视为不通过。"""
    if not expected_hex:
        return False
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest().lower() == str(expected_hex).strip().lower()


def fetch_manifest(url, timeout=_DEF_TIMEOUT):
    """GET 远端更新清单 JSON；网络/解析失败软返回 None（不抛）。"""
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def download(url, dest, progress_cb=None, timeout=_DEF_TIMEOUT):
    """流式下载到 dest（边下边回调进度）。progress_cb(done_bytes, total_bytes)。

    返回 dest(Path)。下载到 .part 临时文件后原子改名，避免半截文件被当成成品。
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0) or 0)
        done = 0
        with open(part, "wb") as f:
            for chunk in r.iter_content(chunk_size=_CHUNK):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
    part.replace(dest)
    return dest


def launch_installer(path):
    """拉起已下载并校验过的 Inno 安装器（静默就地升级），与当前进程脱钩。

    Windows：DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP，使安装器在 app 退出后续命。
    /SILENT 静默、/NORESTART 不自行重启系统（重启 app 交给 installer 的 [Run] 项）。
    非 Windows 不支持（产品仅 Windows），直接抛。
    """
    flags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(path), "/SILENT", "/NORESTART"],
                     creationflags=flags, close_fds=True)
