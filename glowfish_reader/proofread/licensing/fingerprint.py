# -*- coding: utf-8 -*-
"""机器指纹：稳定且不可逆（仅传哈希）。Windows 取 MachineGuid + 主机名；跨平台兜底 MAC。"""
import hashlib, platform, uuid


def fingerprint_from_parts(parts) -> str:
    items = [p for p in parts if p]
    return hashlib.sha256("|".join(items).encode("utf-8")).hexdigest()


def _machine_guid() -> str:
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           r"SOFTWARE\Microsoft\Cryptography")
        v, _ = winreg.QueryValueEx(k, "MachineGuid")
        return str(v)
    except Exception:
        return ""


def machine_fingerprint() -> str:
    parts = [_machine_guid(), platform.node(), f"{uuid.getnode():x}"]
    return fingerprint_from_parts(parts)
