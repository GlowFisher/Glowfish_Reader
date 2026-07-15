import asyncio
import hashlib
import json
from pathlib import Path

import content_api
import library_api


class _Ctx:
    def __init__(self, work: Path):
        self.work = work
        self.notebooks_path = work / "notebooks.json"
        self.progress_path = work / "_import_progress.json"

    def reg(self, batch):
        path = self.work / batch / "proof.json"
        if not path.exists():
            return None
        proof = json.loads(path.read_text(encoding="utf-8"))
        return {"proof_path": str(path), "image_dir": proof.get("image_dir", str(path.parent / "_src"))}


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _proof(path, image_dir=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"batch": path.parent.name, "image_dir": image_dir or str(path.parent / "_src"), "pages": [{
        "page_id": "p1", "order": ["l1", "l2"], "lines": [
            {"id": "l1", "text": "學術，搜索測試。", "deleted": False},
            {"id": "l2", "text": "搜索測試", "deleted": True},
        ]}]}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_library_search_uses_static_proof_and_is_read_only_on_cold_start(tmp_path):
    ctx = _Ctx(tmp_path)
    proof_path = tmp_path / "doc1" / "proof.json"
    _proof(proof_path)
    before = _sha(proof_path)
    result = asyncio.run(library_api.library_search(_Req({"query": "学术搜索"}), ctx))
    assert [(h["text"], h["start"], h["end"]) for h in result["hits"]] == [("學術，搜索測試。", 0, 5)]
    assert _sha(proof_path) == before
    assert not ctx.notebooks_path.exists()
    assert not ctx.progress_path.exists()


def test_load_existing_never_calls_ocr_or_rewrites_stale_paths(tmp_path, monkeypatch):
    ctx = _Ctx(tmp_path)
    proof_path = tmp_path / "doc1" / "proof.json"
    _proof(proof_path, image_dir="D:/stale/location")
    before = _sha(proof_path)
    monkeypatch.setattr(content_api, "_ensure_recog", lambda *a, **k: (_ for _ in ()).throw(AssertionError("OCR called")))
    content_api.load_existing("doc1", ctx)
    assert _sha(proof_path) == before
    assert not ctx.progress_path.exists()


def test_frontend_has_save_flush_and_element_boundary_selection_support():
    static = Path(__file__).resolve().parents[2] / "components" / "ui" / "dist"
    db = (static / "db.js").read_text(encoding="utf-8")
    search = (static / "search.js").read_text(encoding="utf-8")
    ann = (static / "annotations.js").read_text(encoding="utf-8")
    assert "async function gfAwaitSave()" in db
    assert "await gfDiskSave()" in db
    assert "await gfAwaitSave()" in search
    assert "pre.selectNodeContents(editable)" in ann
    assert "pre.setEnd(node, offset)" in ann
