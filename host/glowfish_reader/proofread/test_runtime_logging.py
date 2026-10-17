# -*- coding: utf-8 -*-
import inspect
import logging
import sys
import threading
from types import SimpleNamespace

import appconfig
import desktop_app
import runtime_logging


def test_runtime_logging_writes_utf8_message_under_data_root(monkeypatch, tmp_path):
    monkeypatch.setattr(appconfig, "data_root", lambda: tmp_path)
    path = runtime_logging.configure_runtime_logging("ocr")

    logging.getLogger("release-test").error("OCR 诊断记录")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert path == tmp_path / "logs" / "ocr.log"
    assert "OCR 诊断记录" in path.read_text(encoding="utf-8")


def test_runtime_logging_installs_process_and_thread_hooks(monkeypatch, tmp_path):
    monkeypatch.setattr(appconfig, "data_root", lambda: tmp_path)
    runtime_logging.configure_runtime_logging("desktop")

    assert sys.excepthook is runtime_logging.log_exception
    assert threading.excepthook is runtime_logging.log_thread_exception

    error = RuntimeError("后台预热异常")
    try:
        raise error
    except RuntimeError as caught:
        runtime_logging.log_thread_exception(SimpleNamespace(
            exc_type=RuntimeError,
            exc_value=caught,
            exc_traceback=caught.__traceback__,
            thread=SimpleNamespace(name="prewarm-test"),
        ))
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = (tmp_path / "logs" / "desktop.log").read_text(encoding="utf-8")
    assert "Unhandled exception in thread prewarm-test" in text
    assert "后台预热异常" in text


def test_desktop_logging_bootstrap_is_best_effort(monkeypatch):
    def fail(_mode):
        raise OSError("日志目录不可写")

    monkeypatch.setattr(runtime_logging, "configure_runtime_logging", fail)
    assert desktop_app._configure_runtime_logging("desktop") is None

def test_desktop_and_server_entrypoints_request_distinct_logs():
    assert '_configure_runtime_logging("desktop")' in inspect.getsource(desktop_app.run)
    assert '_configure_runtime_logging("server")' in inspect.getsource(desktop_app._serve_headless)