# -*- coding: utf-8 -*-
"""文件 IO 沙箱：把用户给定的相对路径约束在 _work/ 内，封堵路径穿越。

网页版下前端只传 batch 名 + _work 内相对路径，绝不接受绝对路径 / `..` 逃逸 / 符号链接逃逸。
safe_join 的所有片段都相对 WORK_ROOT（=_work）解析，故调用方**不要**再带 "_work" 前缀。
"""
import re
from pathlib import Path

from fastapi import HTTPException

import appconfig

# 数据根统一由 appconfig 决定（开发态=源码 _work/，打包态=%APPDATA%）。
WORK_ROOT = appconfig.data_root().resolve()
WORK_ROOT.mkdir(parents=True, exist_ok=True)

_DRIVE = re.compile(r"^[A-Za-z]:")
_BAD = re.compile(r'[\\/:*?"<>|]+')
# Windows 保留设备名（作目录名会失败）；智能拆分按文件名建 batch 后须规避
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_batch(name):
    """规范化 batch 名：去非法字符、拒空 / `.` / `..`（用于按名查既有批次）。"""
    name = _BAD.sub("_", (name or "").strip())
    if not name or name in (".", ".."):
        raise HTTPException(400, "非法批次名")
    return name


def coerce_batch(name):
    """强制规范化 batch 名：去非法字符 + Windows 禁的结尾点/空格 + 保留名规避 + 限长；
    空 / `.` / `..` 兜底为 'import'（用于生成新批次名，目录名安全）。"""
    name = _BAD.sub("_", (name or "").strip()).rstrip(". ")
    if name in ("", ".", ".."):
        return "import"
    if name.upper() in _RESERVED:
        name = "_" + name
    return name[:120]


def safe_rel(rel):
    """规范化用户上传的相对路径（webkitRelativePath）：逐段去非法字符、丢弃 `.`/`..`/空段。

    返回安全的相对路径（POSIX 斜杠）；全部段被丢弃时兜底为 'file'。仅作字符串净化，
    真正的越界拦截仍由 safe_join 的 resolve()+relative_to 兜底。"""
    parts = []
    for seg in str(rel or "").replace("\\", "/").split("/"):
        seg = _BAD.sub("_", seg.strip())
        if seg in ("", ".", ".."):
            continue
        parts.append(seg)
    return "/".join(parts) if parts else "file"


def safe_join(*parts):
    """把相对片段拼到 WORK_ROOT 下并 resolve；越界即抛 400。返回解析后的绝对 Path。"""
    p = WORK_ROOT
    for part in parts:
        part = str(part).replace("\\", "/")
        if part.startswith("/") or _DRIVE.match(part):
            raise HTTPException(400, "不允许绝对路径")
        p = p / part
    rp = p.resolve()
    try:
        rp.relative_to(WORK_ROOT)
    except ValueError:
        raise HTTPException(400, "路径越界")
    return rp


def within_work(path):
    """已存在的绝对路径是否落在 WORK_ROOT 内（校验 proof 内 image 字段，防越界出图）。"""
    try:
        Path(path).resolve().relative_to(WORK_ROOT)
        return True
    except (ValueError, OSError):
        return False
