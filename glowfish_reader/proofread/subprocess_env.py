# -*- coding: utf-8 -*-
"""Shared environment setup for local OCR subprocesses."""
import logging
import os
import threading

import appconfig
import paddlex_cache


_LOG = logging.getLogger("glowfish.ocr.cache")
_PREPARE_LOCK = threading.Lock()
_PREPARED_PATH = None
_LEGACY_CLEANUP_DONE = False

_PROXY_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def prepare_ocr_environment(*, cleanup_legacy=False):
    """Configure one drive-free cache path before spawning any OCR worker."""
    global _PREPARED_PATH, _LEGACY_CLEANUP_DONE
    with _PREPARE_LOCK:
        if cleanup_legacy and not _LEGACY_CLEANUP_DONE:
            try:
                removed = paddlex_cache.cleanup_legacy_drive_aliases(
                    appconfig.known_data_roots()
                )
                if removed:
                    _LOG.info("Removed legacy Glowfish drive aliases: %s", removed)
            except Exception:
                _LOG.exception("Legacy Glowfish drive cleanup failed")
            finally:
                _LEGACY_CLEANUP_DONE = True

        if _PREPARED_PATH is not None:
            return _PREPARED_PATH
        try:
            _PREPARED_PATH = paddlex_cache.configure_paddlex_cache(
                appconfig.data_root()
            )
        except Exception:
            _LOG.exception("No drive-free PaddleX cache could be prepared")
            return None
        return _PREPARED_PATH


def clean_subprocess_env():
    prepare_ocr_environment()
    env = dict(os.environ)
    for key in _PROXY_VARS:
        env[key] = ""
    env["NO_PROXY"] = "*"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env
