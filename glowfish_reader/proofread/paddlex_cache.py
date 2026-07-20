"""Validated PaddleX cache selection for source and frozen Windows runtimes."""

from __future__ import annotations

import atexit
import os
import subprocess
from functools import partial
from pathlib import Path

try:
    from . import windows_process
except ImportError:  # Direct legacy-script execution adds this directory to sys.path.
    import windows_process


_CACHE_ENV = "PADDLE_PDX_CACHE_HOME"
_DRIVE_LETTERS = "ZYXWVUTSRQPONMLKJIH"


def _is_ascii_path(path: Path) -> bool:
    try:
        str(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _remove_subst(runner, drive: str) -> None:
    try:
        runner(
            ["subst", drive, "/D"],
            purpose="subst-cleanup",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        pass


def configure_paddlex_cache(
    data_root,
    *,
    environ=None,
    platform_name=None,
    runner=None,
    register_cleanup=None,
    ensure_directory=None,
) -> Path:
    """Select a writable PaddleX cache and export it to the current process.

    Non-ASCII Windows profiles use a temporary ``subst`` alias because some
    PaddleX/ONNX paths still fail on Unicode. A drive is accepted only after
    ``subst`` exits successfully and the cache directory is actually usable.
    """
    environ = os.environ if environ is None else environ
    platform_name = os.name if platform_name is None else platform_name
    runner = windows_process.run if runner is None else runner
    register_cleanup = atexit.register if register_cleanup is None else register_cleanup
    ensure_directory = _ensure_directory if ensure_directory is None else ensure_directory

    configured = environ.get(_CACHE_ENV)
    if configured:
        configured_path = Path(configured)
        try:
            ensure_directory(configured_path)
        except OSError:
            environ.pop(_CACHE_ENV, None)
        else:
            return configured_path

    root = Path(data_root)
    ensure_directory(root)
    direct_cache = root / "paddlex_cache"

    if platform_name == "nt" and not _is_ascii_path(root):
        for letter in _DRIVE_LETTERS:
            drive = f"{letter}:"
            try:
                completed = runner(
                    ["subst", drive, str(root)],
                    purpose="subst",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                completed.check_returncode()
            except (OSError, subprocess.SubprocessError):
                continue

            aliased_cache = Path(f"{drive}\\") / "paddlex_cache"
            try:
                ensure_directory(aliased_cache)
            except OSError:
                _remove_subst(runner, drive)
                continue

            environ[_CACHE_ENV] = str(aliased_cache)
            register_cleanup(partial(_remove_subst, runner, drive))
            return aliased_cache

    ensure_directory(direct_cache)
    environ[_CACHE_ENV] = str(direct_cache)
    return direct_cache
