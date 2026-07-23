import sys
from pathlib import Path


PROOFREAD = Path(__file__).resolve().parents[1] / "glowfish_reader" / "proofread"
sys.path.insert(0, str(PROOFREAD))

import appconfig


def _frozen(monkeypatch, appdata):
    monkeypatch.setattr(appconfig, "is_frozen", lambda: True)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.delenv("SHUPAI_DATA_DIR", raising=False)


def test_new_user_uses_english_data_directory(tmp_path, monkeypatch):
    _frozen(monkeypatch, tmp_path)

    assert appconfig._resolve_data_root() == tmp_path / "Glowfish Reader"


def test_existing_english_directory_has_highest_precedence(tmp_path, monkeypatch):
    _frozen(monkeypatch, tmp_path)
    candidates = appconfig.known_data_roots()
    for candidate in candidates:
        candidate.mkdir()

    assert appconfig._resolve_data_root() == tmp_path / "Glowfish Reader"


def test_current_chinese_directory_is_preserved_for_upgrade(tmp_path, monkeypatch):
    _frozen(monkeypatch, tmp_path)
    current = tmp_path / "Glowfish Reader 史料阅读器"
    current.mkdir()

    assert appconfig._resolve_data_root() == current


def test_oldest_chinese_directory_is_preserved_for_upgrade(tmp_path, monkeypatch):
    _frozen(monkeypatch, tmp_path)
    oldest = tmp_path / "GlowFish史料阅读器"
    oldest.mkdir()

    assert appconfig._resolve_data_root() == oldest


def test_current_chinese_directory_wins_over_oldest(tmp_path, monkeypatch):
    _frozen(monkeypatch, tmp_path)
    current = tmp_path / "Glowfish Reader 史料阅读器"
    oldest = tmp_path / "GlowFish史料阅读器"
    current.mkdir()
    oldest.mkdir()

    assert appconfig._resolve_data_root() == current


def test_explicit_data_root_always_wins(tmp_path, monkeypatch):
    _frozen(monkeypatch, tmp_path)
    explicit = tmp_path / "显式数据"
    monkeypatch.setenv("SHUPAI_DATA_DIR", str(explicit))
    for candidate in appconfig.known_data_roots():
        candidate.mkdir()

    assert appconfig._resolve_data_root() == explicit
