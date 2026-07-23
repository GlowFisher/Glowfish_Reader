"""Drive-free PaddleX cache selection for source and frozen Windows runtimes."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import uuid
from ctypes import wintypes
from pathlib import Path


_CACHE_ENV = "PADDLE_PDX_CACHE_HOME"
_LEGACY_DRIVE_LETTERS = "ZYXWVUTSRQPONMLKJIH"
_LOG = logging.getLogger("glowfish.ocr.cache")


def _is_ascii_path(path: Path) -> bool:
    try:
        str(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / f".glowfish-write-probe-{uuid.uuid4().hex}.tmp"
    try:
        with probe.open("xb") as stream:
            stream.write(b"ok")
            stream.flush()
    finally:
        probe.unlink(missing_ok=True)


def _current_user_sid() -> str:
    if os.name != "nt":
        return ""

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class TOKEN_USER(ctypes.Structure):
        _fields_ = [("User", SID_AND_ATTRIBUTES)]

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        error = ctypes.get_last_error()
        if not required.value or error not in {0, 122}:
            raise ctypes.WinError(error)
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token, 1, buffer, required.value, ctypes.byref(required)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        token_user = ctypes.cast(buffer, ctypes.POINTER(TOKEN_USER)).contents
        sid_text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(
            token_user.User.Sid, ctypes.byref(sid_text)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return sid_text.value
        finally:
            kernel32.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
    finally:
        kernel32.CloseHandle(token)


def _secure_cache_directory(path: Path, user_sid: str) -> None:
    """Protect a per-user cache from other unprivileged local users."""
    if os.name != "nt":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi32.SetFileSecurityW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    advapi32.SetFileSecurityW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    sddl = (
        "D:P"
        "(A;OICI;FA;;;SY)"
        "(A;OICI;FA;;;BA)"
        f"(A;OICI;FA;;;{user_sid})"
    )
    descriptor = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, ctypes.byref(descriptor), None
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        dacl_information = 0x00000004 | 0x80000000
        if not advapi32.SetFileSecurityW(
            str(path), dacl_information, descriptor
        ):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.LocalFree(descriptor)

def _cache_candidates(
    data_root: Path,
    *,
    environ,
    platform_name: str,
    program_data,
    system_root,
    user_sid,
):
    if platform_name == "nt":
        sid = user_sid or _current_user_sid()
        program_data_root = program_data or environ.get("PROGRAMDATA")
        if program_data_root:
            candidate = Path(program_data_root) / "GlowfishReader" / "Cache" / sid
            if _is_ascii_path(candidate):
                yield "programdata", candidate, True, sid
        windows_root = system_root or environ.get("SystemRoot") or environ.get("WINDIR")
        if windows_root:
            candidate = Path(windows_root) / "Temp" / "GlowfishReader" / sid
            if _is_ascii_path(candidate):
                yield "system-temp", candidate, True, sid
    yield "data-root", data_root / "paddlex_cache", False, ""


def configure_paddlex_cache(
    data_root,
    *,
    environ=None,
    platform_name=None,
    runner=None,
    register_cleanup=None,
    ensure_directory=None,
    program_data=None,
    system_root=None,
    user_sid=None,
    secure_directory=None,
) -> Path:
    """Select a writable PaddleX cache without creating a drive alias.

    ``runner`` and ``register_cleanup`` remain accepted for compatibility with
    older callers, but are intentionally unused.
    """
    del runner, register_cleanup
    environ = os.environ if environ is None else environ
    platform_name = os.name if platform_name is None else platform_name
    ensure_directory = _ensure_directory if ensure_directory is None else ensure_directory
    secure_directory = (
        _secure_cache_directory if secure_directory is None else secure_directory
    )

    configured = environ.get(_CACHE_ENV)
    if configured:
        configured_path = Path(configured)
        try:
            ensure_directory(configured_path)
        except OSError:
            environ.pop(_CACHE_ENV, None)
            _LOG.warning("Configured PaddleX cache is unusable: %s", configured_path)
        else:
            _LOG.info("PaddleX cache selected source=explicit path=%s", configured_path)
            return configured_path

    root = Path(data_root)
    failures = []
    for source, candidate, protect, sid in _cache_candidates(
        root,
        environ=environ,
        platform_name=platform_name,
        program_data=program_data,
        system_root=system_root,
        user_sid=user_sid,
    ):
        try:
            ensure_directory(candidate)
            if protect:
                secure_directory(candidate, sid)
                ensure_directory(candidate)
        except (OSError, ValueError) as exc:
            failures.append(f"{source}={candidate}: {exc}")
            _LOG.warning(
                "PaddleX cache candidate rejected source=%s path=%s error=%r",
                source,
                candidate,
                exc,
            )
            continue
        environ[_CACHE_ENV] = str(candidate)
        _LOG.info("PaddleX cache selected source=%s path=%s", source, candidate)
        return candidate

    raise OSError("No writable PaddleX cache without drive mapping: " + "; ".join(failures))


def _query_dos_device(drive: str) -> str:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.QueryDosDeviceW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    kernel32.QueryDosDeviceW.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    size = kernel32.QueryDosDeviceW(drive, buffer, len(buffer))
    if not size:
        error = ctypes.get_last_error()
        if error in {2, 3}:
            return ""
        raise ctypes.WinError(error)
    return buffer.value


def _remove_dos_device(drive: str, raw_target: str) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.DefineDosDeviceW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
    ]
    kernel32.DefineDosDeviceW.restype = wintypes.BOOL
    flags = 0x00000001 | 0x00000002 | 0x00000004
    if not kernel32.DefineDosDeviceW(flags, drive, raw_target):
        raise ctypes.WinError(ctypes.get_last_error())


def _other_glowfish_instance_running() -> bool:
    if os.name != "nt":
        return False
    current_pid = os.getpid()
    executable_name = Path(sys.executable).name.lower()

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return True
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            process_name = entry.szExeFile.lower()
            if entry.th32ProcessID != current_pid and (
                process_name == executable_name
                or process_name.startswith("glowfish reader")
            ):
                return True
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return False
    finally:
        kernel32.CloseHandle(snapshot)

def _normalize_device_target(raw_target: str) -> str:
    target = raw_target[4:] if raw_target.startswith("\\??\\") else raw_target
    return os.path.normcase(os.path.abspath(target.rstrip("\\/")))


def cleanup_legacy_drive_aliases(
    data_roots,
    *,
    platform_name=None,
    query_device=None,
    remove_device=None,
    other_instance_running=None,
):
    """Remove only orphaned Glowfish ``subst`` aliases from older releases."""
    platform_name = os.name if platform_name is None else platform_name
    if platform_name != "nt":
        return []
    other_instance_running = (
        _other_glowfish_instance_running
        if other_instance_running is None
        else other_instance_running
    )
    if other_instance_running():
        _LOG.info("Legacy drive cleanup skipped: another Glowfish process is running")
        return []

    query_device = _query_dos_device if query_device is None else query_device
    remove_device = _remove_dos_device if remove_device is None else remove_device
    accepted_targets = {
        os.path.normcase(os.path.abspath(str(Path(root)).rstrip("\\/")))
        for root in data_roots
    }
    removed = []
    for letter in _LEGACY_DRIVE_LETTERS:
        drive = f"{letter}:"
        try:
            raw_target = query_device(drive)
            if not raw_target or _normalize_device_target(raw_target) not in accepted_targets:
                continue
            remove_device(drive, raw_target)
            removed.append(drive)
            _LOG.info("Removed orphaned Glowfish drive alias drive=%s", drive)
        except OSError as exc:
            _LOG.warning("Legacy drive cleanup failed drive=%s error=%r", drive, exc)
    return removed
