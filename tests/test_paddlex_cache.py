import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


PROOFREAD = Path(__file__).resolve().parents[1] / "glowfish_reader" / "proofread"
sys.path.insert(0, str(PROOFREAD))

from paddlex_cache import cleanup_legacy_drive_aliases, configure_paddlex_cache


SID = "S-1-5-21-1000"


def _reject_subprocess(*_args, **_kwargs):
    raise AssertionError("cache selection must not invoke a subprocess")


def test_windows_uses_private_programdata_cache_without_drive_alias(tmp_path):
    env = {"PROGRAMDATA": str(tmp_path / "ProgramData"), "SystemRoot": "C:/Windows"}
    secured = []

    result = configure_paddlex_cache(
        tmp_path / "用户数据",
        environ=env,
        platform_name="nt",
        runner=_reject_subprocess,
        program_data=env["PROGRAMDATA"],
        user_sid=SID,
        secure_directory=lambda path, sid: secured.append((Path(path), sid)),
    )

    expected = Path(env["PROGRAMDATA"]) / "GlowfishReader" / "Cache" / SID
    assert result == expected
    assert result.is_dir()
    assert env["PADDLE_PDX_CACHE_HOME"] == str(expected)
    assert secured == [(expected, SID)]


def test_programdata_failure_falls_back_to_system_temp(tmp_path):
    env = {}
    program_data = tmp_path / "ProgramData"
    system_root = tmp_path / "Windows"

    def ensure(path):
        path = Path(path)
        if program_data in path.parents:
            raise PermissionError(13, "programdata denied", str(path))
        path.mkdir(parents=True, exist_ok=True)

    result = configure_paddlex_cache(
        tmp_path / "用户数据",
        environ=env,
        platform_name="nt",
        runner=_reject_subprocess,
        ensure_directory=ensure,
        program_data=program_data,
        system_root=system_root,
        user_sid=SID,
        secure_directory=lambda _path, _sid: None,
    )

    assert result == system_root / "Temp" / "GlowfishReader" / SID
    assert env["PADDLE_PDX_CACHE_HOME"] == str(result)


def test_system_cache_failures_fall_back_to_data_root(tmp_path):
    env = {}
    program_data = tmp_path / "ProgramData"
    system_root = tmp_path / "Windows"
    data_root = tmp_path / "用户数据"

    def ensure(path):
        path = Path(path)
        if program_data in path.parents or system_root in path.parents:
            raise PermissionError(13, "system cache denied", str(path))
        path.mkdir(parents=True, exist_ok=True)

    result = configure_paddlex_cache(
        data_root,
        environ=env,
        platform_name="nt",
        runner=_reject_subprocess,
        ensure_directory=ensure,
        program_data=program_data,
        system_root=system_root,
        user_sid=SID,
        secure_directory=lambda _path, _sid: None,
    )

    assert result == data_root / "paddlex_cache"
    assert env["PADDLE_PDX_CACHE_HOME"] == str(result)


def test_valid_explicit_cache_is_preserved(tmp_path):
    explicit = tmp_path / "configured-cache"
    env = {"PADDLE_PDX_CACHE_HOME": str(explicit)}

    result = configure_paddlex_cache(
        tmp_path / "ignored", environ=env, runner=_reject_subprocess
    )

    assert result == explicit
    assert explicit.is_dir()


def test_unusable_explicit_cache_uses_programdata(tmp_path):
    explicit = tmp_path / "unusable"
    program_data = tmp_path / "ProgramData"
    env = {"PADDLE_PDX_CACHE_HOME": str(explicit)}

    def ensure(path):
        path = Path(path)
        if path == explicit:
            raise PermissionError(13, "denied", str(path))
        path.mkdir(parents=True, exist_ok=True)

    result = configure_paddlex_cache(
        tmp_path / "data",
        environ=env,
        platform_name="nt",
        runner=_reject_subprocess,
        ensure_directory=ensure,
        program_data=program_data,
        user_sid=SID,
        secure_directory=lambda _path, _sid: None,
    )

    assert result == program_data / "GlowfishReader" / "Cache" / SID


def test_all_candidates_fail_with_diagnostic_error(tmp_path):
    env = {}

    def reject(path):
        raise PermissionError(13, "denied", str(path))

    with pytest.raises(OSError, match="No writable PaddleX cache without drive mapping"):
        configure_paddlex_cache(
            tmp_path / "data",
            environ=env,
            platform_name="nt",
            runner=_reject_subprocess,
            ensure_directory=reject,
            program_data=tmp_path / "ProgramData",
            system_root=tmp_path / "Windows",
            user_sid=SID,
            secure_directory=lambda _path, _sid: None,
        )
    assert "PADDLE_PDX_CACHE_HOME" not in env


def test_concurrent_callers_share_one_cache_path(tmp_path):
    env = {}
    program_data = tmp_path / "ProgramData"

    def configure():
        return configure_paddlex_cache(
            tmp_path / "用户数据",
            environ=env,
            platform_name="nt",
            runner=_reject_subprocess,
            program_data=program_data,
            user_sid=SID,
            secure_directory=lambda _path, _sid: None,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: configure(), range(24)))

    assert set(results) == {program_data / "GlowfishReader" / "Cache" / SID}


def test_cleanup_removes_only_exact_legacy_target(tmp_path):
    legacy = tmp_path / "GlowFish史料阅读器"
    unrelated = tmp_path / "unrelated"
    mappings = {
        "Z:": "\\??\\" + str(legacy),
        "Y:": "\\??\\" + str(unrelated),
    }
    removed = []

    result = cleanup_legacy_drive_aliases(
        [legacy],
        platform_name="nt",
        query_device=lambda drive: mappings.get(drive, ""),
        remove_device=lambda drive, target: removed.append((drive, target)),
        other_instance_running=lambda: False,
    )

    assert result == ["Z:"]
    assert removed == [("Z:", mappings["Z:"])]


def test_cleanup_skips_everything_while_another_instance_runs(tmp_path):
    queried = []

    result = cleanup_legacy_drive_aliases(
        [tmp_path / "GlowFish史料阅读器"],
        platform_name="nt",
        query_device=lambda drive: queried.append(drive),
        remove_device=lambda _drive, _target: None,
        other_instance_running=lambda: True,
    )

    assert result == []
    assert queried == []
