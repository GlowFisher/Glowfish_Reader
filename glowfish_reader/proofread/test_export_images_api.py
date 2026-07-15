import io
import json
import zipfile

import pytest
from docx import Document
from fastapi import HTTPException
from PIL import Image

import safefs
from export_api import _export_notebook, _export_selected


def _fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(safefs, "WORK_ROOT", tmp_path.resolve())
    paths = {}
    for batch, pid in (("a", "p1"), ("b", "p2")):
        src = tmp_path / batch / "_src"
        src.mkdir(parents=True)
        Image.new("RGB", (24, 24), "white").save(src / f"{pid}.png")
        proof = {"batch": batch, "image_dir": str(src), "pages": [{
            "page_id": pid, "image": f"_img/{pid}.jpg",
            "lines": [{"id": pid, "text": pid, "deleted": False, "para_break": True}],
            "order": [pid],
        }]}
        path = tmp_path / batch / "proof.json"
        path.write_text(json.dumps(proof), encoding="utf-8")
        paths[batch] = path

    class Ctx:
        def reg(self, batch):
            return {"proof_path": str(paths[batch])} if batch in paths else None
    return Ctx()


def test_selected_and_notebook_docx_embed_source_images(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch)
    selected = _export_selected(ctx, {"selected": [{"batch": "a", "page_ids": ["p1"]}]}, "docx", True)
    notebook = _export_notebook(ctx, {"batches": ["a", "b"]}, "docx", True)
    assert len(Document(io.BytesIO(selected.body)).inline_shapes) == 1
    assert len(Document(io.BytesIO(notebook.body)).inline_shapes) == 2


def test_markdown_zip_contains_resolved_image(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch)
    response = _export_selected(ctx, {"selected": [{"batch": "a", "page_ids": ["p1"]}]}, "md", True)
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        assert any(name.endswith("_原图/0001_p1.png") for name in archive.namelist())


def test_requested_images_fail_clearly_when_all_are_missing(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch)
    (tmp_path / "a" / "_src" / "p1.png").unlink()
    with pytest.raises(HTTPException) as exc:
        _export_selected(ctx, {"selected": [{"batch": "a", "page_ids": ["p1"]}]}, "docx", True)
    assert exc.value.status_code == 422
    detail = exc.value.detail
    assert detail["code"] == "export_images_missing"
    assert detail["missing_count"] == 1
    assert detail["pages"] == [{"batch": "选中页面", "page_id": "p1"}]
