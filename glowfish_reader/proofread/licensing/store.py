# -*- coding: utf-8 -*-
"""授权缓存：data_root/license.json。含 cred 与单调最大时间戳（防时钟回拨）。

并发安全：进程内 _LOCK 串行化读改写，os.replace 原子落盘（杜绝并发半截写）。
损坏即回退默认（fail-closed），不保留陈旧凭据——避免掩盖服务端吊销。"""
import os
import json
import time
import tempfile
import threading
from pathlib import Path

_DEFAULTS = {"account_cred": None, "account_session_id": None, "account": None,
             "max_seen_ts": 0}
_LOCK = threading.RLock()


def load(path: str) -> dict:
    with _LOCK:
        d = dict(_DEFAULTS)
        p = Path(path)
        if p.exists():
            try:
                d.update(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass                                 # 损坏即回退默认（fail-closed）
        return d


def save(path: str, d: dict) -> None:
    with _LOCK:
        merged = load(path); merged.update(d)
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".lic", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(merged, ensure_ascii=False, indent=2))
            for attempt in range(3):                 # Windows 下目标可能被杀软/另进程短暂占用 → 原子替换重试
                try:
                    os.replace(tmp, str(p)); tmp = None; break
                except PermissionError:
                    if attempt == 2:
                        raise
                    time.sleep(0.05)
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass


def bump_seen(path: str, ts: int) -> int:
    d = load(path)
    cur = max(int(d.get("max_seen_ts", 0)), int(ts))
    save(path, {"max_seen_ts": cur})
    return cur
