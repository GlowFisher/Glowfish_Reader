# -*- coding: utf-8 -*-
"""Persistent diagnostics for windowed desktop and OCR child processes."""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

import appconfig


def log_exception(exc_type, exc, tb):
    logging.getLogger("glowfish.crash").error("Unhandled exception", exc_info=(exc_type, exc, tb))


def log_thread_exception(args):
    """Persist otherwise-unhandled background-thread failures."""
    if args.exc_type is SystemExit:
        return
    name = getattr(args.thread, "name", "unknown")
    logging.getLogger("glowfish.crash").error(
        "Unhandled exception in thread %s", name,
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def configure_runtime_logging(mode: str) -> Path:
    """Configure a UTF-8 rotating log under the user data root."""
    log_dir = appconfig.data_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{mode}.log"
    handler = RotatingFileHandler(path, encoding="utf-8", maxBytes=2_000_000, backupCount=5)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    sys.excepthook = log_exception
    threading.excepthook = log_thread_exception
    logging.getLogger("glowfish.runtime").info("runtime logging initialized: %s", mode)
    return path
