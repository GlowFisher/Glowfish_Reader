import json

import pytest

import document_repository
from document_repository import DocumentRepository


def _repository(tmp_path, page_count):
    proof = {
        "batch": "transform",
        "script": "s",
        "pages": [
            {
                "page_id": f"page-{index + 1}",
                "lines": [{"id": f"line-{index}", "text": f"text {index}"}],
                "order": [f"line-{index}"],
            }
            for index in range(page_count)
        ],
    }
    (tmp_path / "proof.json").write_text(json.dumps(proof), encoding="utf-8")
    repo = DocumentRepository(tmp_path)
    repo.load_meta()
    return repo


def test_document_transform_publishes_metadata_once(tmp_path, monkeypatch):
    repo = _repository(tmp_path, 500)
    original_atomic = document_repository._atomic_json
    metadata_writes = 0

    def count_atomic(path, value):
        nonlocal metadata_writes
        if path == repo.meta_path:
            metadata_writes += 1
        return original_atomic(path, value)

    monkeypatch.setattr(document_repository, "_atomic_json", count_atomic)

    def transform(page, _index):
        page["lines"][0]["text"] += " changed"

    meta = repo.transform_pages(transform, meta_changes={"script": "t"})

    assert metadata_writes == 1
    assert meta["revision"] == 1
    assert meta["script"] == "t"
    assert repo.load_page("page-500")["page"]["lines"][0]["text"].endswith(" changed")


def test_failed_document_transform_keeps_previous_generation_active(tmp_path):
    repo = _repository(tmp_path, 10)
    before = repo.load_meta()

    def transform(page, index):
        page["lines"][0]["text"] = "changed"
        if index == 3:
            raise OSError("simulated transform failure")

    with pytest.raises(OSError):
        repo.transform_pages(transform, meta_changes={"script": "t"})

    after = repo.load_meta()
    assert after == before
    assert repo.load_page("page-1")["page"]["lines"][0]["text"] == "text 0"
