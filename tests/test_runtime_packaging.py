from pathlib import Path


def test_pyinstaller_includes_host_public_package_and_v2_entry():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "glowfish_reader" / "proofread" / "glowfish_reader.spec").read_text(encoding="utf-8")
    assert 'HOST_SRC = os.path.join(HOST_ROOT, "src")' in spec
    assert "pathex=[HERE, ROOT, PIPELINE, HOST_SRC]" in spec
    assert '"glowfish_host", "glowfish_host.app", "glowfish_host.services", "server_v2"' in spec
