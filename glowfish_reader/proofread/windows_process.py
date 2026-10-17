# -*- coding: utf-8 -*-
"""Registered, hidden child-process lifecycle helpers for OCR workers."""

from __future__ import annotations

import atexit
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass


@dataclass
class ChildInfo:
    process: subprocess.Popen
    purpose: str
    job_id: str | None
    started_at: float


_LOCK = threading.RLock()
_CHILDREN: dict[int, ChildInfo] = {}
_STOPPING = threading.Event()
_JOB_HANDLE = None


def hidden_process_kwargs():
    """Return Windows flags that suppress console windows; no-op elsewhere."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def is_stopping():
    return _STOPPING.is_set()


def _job_object():
    """Create the process-wide kill-on-close Job Object lazily on Windows."""
    global _JOB_HANDLE
    if os.name != "nt" or _JOB_HANDLE:
        return _JOB_HANDLE
    try:
        import ctypes
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_job = kernel32.CreateJobObjectW
        create_job.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        create_job.restype = wintypes.HANDLE
        set_info = kernel32.SetInformationJobObject
        set_info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        set_info.restype = wintypes.BOOL
        handle = create_job(None, None)
        if not handle:
            return None
        info = EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        ok = set_info(handle, 9, ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            kernel32.CloseHandle(handle)
            return None
        _JOB_HANDLE = handle
    except Exception:
        _JOB_HANDLE = None
    return _JOB_HANDLE


def _assign_job(process):
    handle = _job_object()
    if not handle:
        return
    try:
        import ctypes
        from ctypes import wintypes
        assign = ctypes.WinDLL("kernel32", use_last_error=True).AssignProcessToJobObject
        assign.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        assign.restype = wintypes.BOOL
        assign(handle, wintypes.HANDLE(int(process._handle)))
    except Exception as exc:
        # 绑定失败意味着主进程退出后子进程不会被连带终止，记录日志便于排查残留进程
        logging.getLogger("glowfish.process").warning(
            "无法将子进程绑定到 Job Object（%s）；主进程退出后该子进程可能残留：%s",
            exc, getattr(process, "pid", None),
        )


def spawn(argv, *, purpose="helper", job_id=None, **kwargs):
    if _STOPPING.is_set():
        raise RuntimeError("application_stopping")
    for key, value in hidden_process_kwargs().items():
        kwargs.setdefault(key, value)
    process = subprocess.Popen(argv, **kwargs)
    with _LOCK:
        _CHILDREN[process.pid] = ChildInfo(process, purpose, job_id, time.monotonic())
    _assign_job(process)
    return process


def unregister(process):
    if process is not None:
        with _LOCK:
            _CHILDREN.pop(getattr(process, "pid", None), None)


def run(argv, *, purpose="helper", job_id=None, timeout=None, **kwargs):
    process = spawn(argv, purpose=purpose, job_id=job_id, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_process(process)
        raise
    finally:
        unregister(process)
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def terminate_process(process, graceful_timeout=3.0, terminate_timeout=3.0):
    if process is None or process.poll() is not None:
        unregister(process)
        return
    try:
        process.wait(timeout=graceful_timeout)
    except subprocess.TimeoutExpired:
        try:
            process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=terminate_timeout)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=1.0)
            except Exception:
                pass
    finally:
        unregister(process)


def shutdown_all():
    _STOPPING.set()
    with _LOCK:
        children = [info.process for info in _CHILDREN.values()]
    for process in children:
        terminate_process(process, graceful_timeout=0.25, terminate_timeout=3.0)
    global _JOB_HANDLE
    if _JOB_HANDLE and os.name == "nt":
        try:
            import ctypes
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(_JOB_HANDLE)
        except Exception:
            pass
        _JOB_HANDLE = None


def reset_for_tests():
    _STOPPING.clear()


atexit.register(shutdown_all)
