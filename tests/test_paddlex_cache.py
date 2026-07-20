import subprocess
from pathlib import Path

from glowfish_ocr.legacy.paddlex_cache import configure_paddlex_cache


def test_failed_subst_is_not_selected_for_non_ascii_data_root(tmp_path):
    env = {}
    commands = []
    directories = []

    def runner(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 1 if command[1] == "Z:" else 0)

    result = configure_paddlex_cache(
        tmp_path / "用户",
        environ=env,
        platform_name="nt",
        runner=runner,
        register_cleanup=lambda _callback: None,
        ensure_directory=lambda path: directories.append(Path(path)),
    )

    assert commands[:2] == [
        ["subst", "Z:", str(tmp_path / "用户")],
        ["subst", "Y:", str(tmp_path / "用户")],
    ]
    assert result == Path("Y:/paddlex_cache")
    assert env["PADDLE_PDX_CACHE_HOME"] == str(result)
    assert Path("Z:/paddlex_cache") not in directories
    assert Path("Y:/paddlex_cache") in directories


def test_alias_is_cleaned_up_when_its_cache_directory_is_unusable(tmp_path):
    env = {}
    commands = []

    def runner(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    def ensure_directory(path):
        if Path(path) == Path("Z:/paddlex_cache"):
            raise OSError(21, "device is not ready")

    result = configure_paddlex_cache(
        tmp_path / "用户",
        environ=env,
        platform_name="nt",
        runner=runner,
        register_cleanup=lambda _callback: None,
        ensure_directory=ensure_directory,
    )

    assert ["subst", "Z:", "/D"] in commands
    assert result == Path("Y:/paddlex_cache")
    assert env["PADDLE_PDX_CACHE_HOME"] == str(result)


def test_unusable_explicit_cache_falls_back_to_data_root(tmp_path):
    env = {"PADDLE_PDX_CACHE_HOME": "Z:/paddlex_cache"}

    def ensure_directory(path):
        if Path(path) == Path("Z:/paddlex_cache"):
            raise OSError(21, "device is not ready")
        Path(path).mkdir(parents=True, exist_ok=True)

    result = configure_paddlex_cache(
        tmp_path,
        environ=env,
        platform_name="nt",
        ensure_directory=ensure_directory,
    )

    assert result == tmp_path / "paddlex_cache"
    assert result.is_dir()
    assert env["PADDLE_PDX_CACHE_HOME"] == str(result)


def test_valid_explicit_cache_is_preserved(tmp_path):
    explicit = tmp_path / "configured-cache"
    env = {"PADDLE_PDX_CACHE_HOME": str(explicit)}

    result = configure_paddlex_cache(tmp_path / "ignored", environ=env)

    assert result == explicit
    assert explicit.is_dir()
    assert env["PADDLE_PDX_CACHE_HOME"] == str(explicit)


def test_existing_but_unwritable_explicit_cache_falls_back(tmp_path, monkeypatch):
    explicit = tmp_path / "configured-cache"
    explicit.mkdir()
    env = {"PADDLE_PDX_CACHE_HOME": str(explicit)}
    original_open = Path.open

    def reject_explicit_probe(path, *args, **kwargs):
        if path.parent == explicit and path.name.startswith(".glowfish-write-probe-"):
            raise PermissionError(13, "permission denied", str(path))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_explicit_probe)
    result = configure_paddlex_cache(tmp_path / "fallback", environ=env)

    assert result == tmp_path / "fallback" / "paddlex_cache"
    assert result.is_dir()
    assert env["PADDLE_PDX_CACHE_HOME"] == str(result)
    assert not list(result.glob(".glowfish-write-probe-*"))


def test_all_failed_aliases_fall_back_to_unicode_data_root(tmp_path):
    env = {}

    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1)

    data_root = tmp_path / "用户"
    result = configure_paddlex_cache(
        data_root,
        environ=env,
        platform_name="nt",
        runner=runner,
    )

    assert result == data_root / "paddlex_cache"
    assert result.is_dir()
    assert env["PADDLE_PDX_CACHE_HOME"] == str(result)
