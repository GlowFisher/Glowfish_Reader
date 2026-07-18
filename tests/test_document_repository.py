import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from document_repository import DocumentConflictError, DocumentRepository


def proof(page_count=3):
    return {
        "batch": "中文 batch",
        "engine": "test",
        "script": "s",
        "pages": [
            {
                "page_id": f"第 {i + 1} 页",
                "image": f"第 {i + 1} 页.png",
                "width": 1200,
                "height": 1800,
                "lines": [{"id": f"l{i}", "text": f"正文 {i}", "text_draft": f"正文 {i}"}],
                "order": [f"l{i}"],
            }
            for i in range(page_count)
        ],
    }


def write_legacy(tmp_path, page_count=3):
    value = proof(page_count)
    (tmp_path / "proof.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return value


def test_migrates_legacy_without_changing_it(tmp_path):
    legacy = write_legacy(tmp_path)
    before = (tmp_path / "proof.json").read_bytes()
    repo = DocumentRepository(tmp_path)

    meta = repo.load_meta()

    assert meta["schema_version"] == 2
    assert len(meta["pages"]) == 3
    assert all("lines" not in page and "file" not in page for page in meta["pages"])
    assert repo.load_full()["pages"] == [{**p, "revision": 0} for p in legacy["pages"]]
    assert (tmp_path / "proof.json").read_bytes() == before


def test_page_save_is_atomic_and_conflict_aware(tmp_path):
    write_legacy(tmp_path)
    repo = DocumentRepository(tmp_path)
    loaded = repo.load_page("第 2 页")
    loaded["page"]["lines"][0]["text"] += " updated"

    saved = repo.save_page("第 2 页", loaded["page"], loaded["revision"])

    assert saved["revision"] == 1
    assert repo.load_page("第 2 页")["page"]["lines"][0]["text"].endswith("updated")
    with pytest.raises(DocumentConflictError):
        repo.save_page("第 2 页", loaded["page"], 0)


def test_different_pages_can_be_saved_without_lost_updates(tmp_path):
    write_legacy(tmp_path, 20)
    repo = DocumentRepository(tmp_path)
    repo.load_meta()

    def update(index):
        page_id = f"第 {index + 1} 页"
        loaded = repo.load_page(page_id)
        loaded["page"]["lines"][0]["text"] = f"changed {index}"
        return repo.save_page(page_id, loaded["page"], loaded["revision"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(update, range(20)))
    assert [repo.load_page(f"第 {i + 1} 页")["page"]["lines"][0]["text"] for i in range(20)] == [
        f"changed {i}" for i in range(20)
    ]


@pytest.mark.parametrize("page_count", [46, 100, 500, 2000])
def test_metadata_response_never_contains_page_body(tmp_path, page_count):
    write_legacy(tmp_path, page_count)
    meta = DocumentRepository(tmp_path).load_meta()
    encoded = json.dumps(meta, ensure_ascii=False)
    assert len(meta["pages"]) == page_count
    assert "正文" not in encoded
    assert "lines" not in encoded
