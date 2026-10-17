# -*- coding: utf-8 -*-
import json
from pathlib import Path

from fastapi import HTTPException
from PIL import Image

import content_api


def _proof(batch, image):
    return {
        "batch": batch,
        "script": "s",
        "image_dir": "",
        "pages": [{
            "page_id": "0001_old",
            "image": image,
            "width": 20,
            "height": 10,
            "lines": [],
            "order": [],
        }],
    }


class FakeCtx:
    def __init__(self, work):
        self.work = Path(work)
        self.progress_path = self.work / "progress.json"

    def read_progress(self):
        if not self.progress_path.exists():
            return {}
        return json.loads(self.progress_path.read_text(encoding="utf-8"))

    def write_progress(self, data):
        self.progress_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def reg(self, batch):
        proof_path = self.work / batch / "proof.json"
        if not proof_path.exists():
            return None
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        return {
            "image_dir": proof.get("image_dir") or str(self.work / batch / "_src"),
            "proof_path": str(proof_path),
            "recog_path": str(self.work / batch / "_recog.json"),
            "engine": proof.get("engine", "paddle"),
        }


def test_get_image_repairs_missing_legacy_absolute_path_from_batch_src(tmp_path, monkeypatch):
    batch = "legacy"
    bdir = tmp_path / batch
    src = bdir / "_src"
    src.mkdir(parents=True)
    Image.new("RGB", (20, 10), "white").save(src / "0001_old.png")
    proof_path = bdir / "proof.json"
    proof_path.write_text(
        json.dumps(_proof(batch, r"D:\old\missing\0001_old.jpg"), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(content_api.safefs, "WORK_ROOT", tmp_path)

    response = content_api.get_image(batch, "0001_old", ctx=FakeCtx(tmp_path))

    repaired = json.loads(proof_path.read_text(encoding="utf-8"))
    assert Path(response.path) == src / "0001_old.png"
    assert repaired["pages"][0]["image"] == "0001_old.png"
    assert repaired["image_dir"] == str(src)


def test_get_image_rejects_external_absolute_path_without_local_copy(tmp_path, monkeypatch):
    batch = "unsafe"
    bdir = tmp_path / batch
    bdir.mkdir()
    (bdir / "proof.json").write_text(
        json.dumps(_proof(batch, r"D:\outside\secret.png"), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(content_api.safefs, "WORK_ROOT", tmp_path)

    try:
        content_api.get_image(batch, "0001_old", ctx=FakeCtx(tmp_path))
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        assert False, "external absolute path should not be served"


def test_load_proof_stores_relative_image_paths_for_new_imports(monkeypatch, tmp_path):
    batch = "newimport"
    image_dir = tmp_path / batch / "_src"
    image_dir.mkdir(parents=True)

    def fake_ensure_recog(ctx, _image_dir, recog_path, engine, request_id=None):
        recog_path.write_text(json.dumps({
            "0001_page": {
                "image": str(image_dir / "0001_page.png"),
                "width": 1,
                "height": 1,
                "lines": [],
            }
        }), encoding="utf-8")
        return engine

    monkeypatch.setattr(content_api, "_ensure_recog", fake_ensure_recog)
    ctx = FakeCtx(tmp_path)

    proof = content_api._load_proof(ctx, batch, image_dir, "src", engine="ppocrv6")

    assert proof["pages"][0]["image"] == "0001_page.png"
    saved = json.loads((tmp_path / batch / "proof.json").read_text(encoding="utf-8"))
    assert saved["pages"][0]["image"] == "0001_page.png"
