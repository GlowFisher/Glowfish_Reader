# -*- coding: utf-8 -*-
"""Shared environment setup for local OCR subprocesses."""
import os


_PROXY_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def clean_subprocess_env():
    env = dict(os.environ)
    for key in _PROXY_VARS:
        env[key] = ""
    env["NO_PROXY"] = "*"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env
