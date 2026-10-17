from __future__ import annotations

import json

from glowfish_reader.proofread import ui_assets


def test_ui_dist_accepts_valid_override_from_shallow_install_path(tmp_path, monkeypatch):
    dist = tmp_path / "ui_dist"
    dist.mkdir()
    (dist / "index.html").write_text("<main>ok</main>", encoding="utf-8")
    (dist / "manifest.json").write_text(
        json.dumps({"files": [{"path": "index.html"}]}),
        encoding="utf-8",
    )

    monkeypatch.setenv("GLOWFISH_UI_DIST", str(dist))
    monkeypatch.delenv("GLOWFISH_WORKSPACE_ROOT", raising=False)
    monkeypatch.setattr(ui_assets, "__file__", "D:/ui_assets.py")

    assert ui_assets.ui_dist() == dist.resolve()
