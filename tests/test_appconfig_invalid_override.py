import sys
from pathlib import Path


PROOFREAD = Path(__file__).resolve().parents[1] / "glowfish_reader" / "proofread"
sys.path.insert(0, str(PROOFREAD))

import appconfig


def test_existing_file_is_not_a_valid_data_directory_override(tmp_path, monkeypatch):
    invalid = tmp_path / "not-a-directory"
    invalid.write_text("file", encoding="utf-8")
    legacy = tmp_path / "Glowfish Reader 史料阅读器"
    legacy.mkdir()

    monkeypatch.setattr(appconfig, "is_frozen", lambda: True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("SHUPAI_DATA_DIR", str(invalid))

    assert appconfig._resolve_data_root() == legacy
