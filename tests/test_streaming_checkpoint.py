import json

import pytest

import document_repository
from document_repository import DocumentRepository


def _repository(tmp_path, page_count):
    proof = {
        "batch": "checkpoint",
        "notes": "document notes",
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


def test_checkpoint_streams_2000_pages_without_load_full(tmp_path, monkeypatch):
    repo = _repository(tmp_path, 2000)
    loaded = repo.load_page("page-2000")
    loaded["page"]["lines"][0]["text"] = "changed final page"
    repo.save_page("page-2000", loaded["page"], loaded["revision"])

    def reject_full_load():
        raise AssertionError("checkpoint must not load the complete document")

    monkeypatch.setattr(repo, "load_full", reject_full_load)
    progress = []
    result = repo.checkpoint(progress=lambda done, total: progress.append((done, total)))

    checkpoint = json.loads(repo.proof_path.read_text(encoding="utf-8"))
    assert result["revision"] == 1
    assert len(checkpoint["pages"]) == 2000
    assert checkpoint["pages"][-1]["lines"][0]["text"] == "changed final page"
    assert progress[-1] == (2000, 2000)
    assert "schema_version" not in checkpoint


def test_checkpoint_replace_failure_preserves_previous_snapshot(tmp_path, monkeypatch):
    repo = _repository(tmp_path, 10)
    previous = repo.proof_path.read_bytes()
    loaded = repo.load_page("page-1")
    loaded["page"]["lines"][0]["text"] = "new text"
    repo.save_page("page-1", loaded["page"], loaded["revision"])
    original_replace = document_repository.os.replace

    def fail_checkpoint_replace(source, destination):
        if destination == repo.proof_path:
            raise OSError("simulated checkpoint replace failure")
        return original_replace(source, destination)

    monkeypatch.setattr(document_repository.os, "replace", fail_checkpoint_replace)
    with pytest.raises(OSError):
        repo.checkpoint()

    assert repo.proof_path.read_bytes() == previous
    assert not list(tmp_path.glob(".proof-checkpoint-*.tmp"))


def test_cancelled_checkpoint_leaves_previous_snapshot_active(tmp_path):
    repo = _repository(tmp_path, 20)
    previous = repo.proof_path.read_bytes()
    calls = 0

    def cancel_after_five_pages():
        nonlocal calls
        calls += 1
        if calls > 5:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        repo.checkpoint(check_cancelled=cancel_after_five_pages)

    assert repo.proof_path.read_bytes() == previous
    assert not list(tmp_path.glob(".proof-checkpoint-*.tmp"))
