import os
import sys
from pathlib import Path


PROOFREAD = Path(__file__).resolve().parents[1] / "glowfish_reader" / "proofread"
sys.path.insert(0, str(PROOFREAD))

import subprocess_env


def _reset_state():
    subprocess_env._PREPARED_PATH = None
    subprocess_env._LEGACY_CLEANUP_DONE = False


def test_main_process_exports_one_cache_for_every_worker(monkeypatch, tmp_path):
    _reset_state()
    cache = tmp_path / "shared-cache"
    configured = []

    def configure(_data_root):
        configured.append(cache)
        monkeypatch.setenv("PADDLE_PDX_CACHE_HOME", str(cache))
        return cache

    monkeypatch.setattr(subprocess_env.appconfig, "data_root", lambda: tmp_path)
    monkeypatch.setattr(
        subprocess_env.paddlex_cache, "configure_paddlex_cache", configure
    )

    first = subprocess_env.prepare_ocr_environment()
    second = subprocess_env.clean_subprocess_env()

    assert first == cache
    assert configured == [cache]
    assert second["PADDLE_PDX_CACHE_HOME"] == str(cache)


def test_legacy_cleanup_runs_once_before_cache_preparation(monkeypatch, tmp_path):
    _reset_state()
    events = []
    cache = tmp_path / "cache"

    monkeypatch.setattr(
        subprocess_env.appconfig,
        "known_data_roots",
        lambda: (tmp_path / "Glowfish Reader",),
    )
    monkeypatch.setattr(subprocess_env.appconfig, "data_root", lambda: tmp_path)
    monkeypatch.setattr(
        subprocess_env.paddlex_cache,
        "cleanup_legacy_drive_aliases",
        lambda roots: events.append(("cleanup", tuple(roots))) or [],
    )
    monkeypatch.setattr(
        subprocess_env.paddlex_cache,
        "configure_paddlex_cache",
        lambda root: events.append(("configure", root)) or cache,
    )

    subprocess_env.prepare_ocr_environment(cleanup_legacy=True)
    subprocess_env.prepare_ocr_environment(cleanup_legacy=True)

    assert events == [
        ("cleanup", (tmp_path / "Glowfish Reader",)),
        ("configure", tmp_path),
    ]


def teardown_module():
    _reset_state()
    os.environ.pop("PADDLE_PDX_CACHE_HOME", None)
