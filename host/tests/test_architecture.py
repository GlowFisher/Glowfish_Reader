from pathlib import Path


def test_component_owned_trees_are_not_duplicated_in_host():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "glowfish_reader" / "proofread" / "static").exists()
    assert not (root / "glowfish_reader" / "license_server").exists()
    assert not (root / "glowfish_reader" / "bench").exists()


def test_server_is_assembly_only_for_ui_and_python_path():
    server = (Path(__file__).resolve().parents[1] / "glowfish_reader" / "proofread" / "server.py").read_text(encoding="utf-8")
    assert "sys.path.insert" not in server
    assert 'HERE / "static"' not in server
    assert "ui_assets.ui_dist()" in server
