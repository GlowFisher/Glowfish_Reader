import json
import zipfile
from pathlib import Path

import document_repository
import export_api
from document_task_manager import DocumentTaskManager


class ExportContext:
    def __init__(self, work):
        self.uid = "test-user"
        self.work = work

    def reg(self, batch):
        proof = self.work / batch / "proof.json"
        return {"proof_path": str(proof)} if proof.is_file() else None


def _write_proof(work: Path, batch: str, page_count: int):
    directory = work / batch
    directory.mkdir(parents=True)
    proof = {
        "batch": batch,
        "source": f"{batch}.pdf",
        "script": "s",
        "pages": [
            {
                "page_id": f"page-{index + 1}",
                "image": f"page-{index + 1}.png",
                "lines": [{"id": f"line-{index}", "text": f"text {index}"}],
                "order": [f"line-{index}"],
            }
            for index in range(page_count)
        ],
    }
    (directory / "proof.json").write_text(
        json.dumps(proof, ensure_ascii=False), encoding="utf-8"
    )


def test_docx_export_task_iterates_pages_without_load_full(tmp_path, monkeypatch):
    _write_proof(tmp_path, "large document", 100)
    manager = DocumentTaskManager(max_workers=1)
    monkeypatch.setattr(export_api, "TASK_MANAGER", manager)

    def reject_full_load(_self):
        raise AssertionError("background DOCX export must not load the full document")

    monkeypatch.setattr(document_repository.DocumentRepository, "load_full", reject_full_load)
    task = export_api._queue_docx_export(
        ExportContext(tmp_path),
        {"scope": "all", "batch": "large document", "name": "large document"},
        page_marks=True,
    )
    task.future.result(timeout=20)

    assert task.state == "done"
    assert task.done == task.total == 100
    assert task.result_path.is_file()
    with zipfile.ZipFile(task.result_path) as archive:
        assert "word/document.xml" in archive.namelist()
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert "text 0" in document_xml
    assert "text 99" in document_xml


def test_selected_docx_task_counts_only_selected_pages(tmp_path, monkeypatch):
    _write_proof(tmp_path, "first", 46)
    _write_proof(tmp_path, "second", 20)
    manager = DocumentTaskManager(max_workers=1)
    monkeypatch.setattr(export_api, "TASK_MANAGER", manager)

    task = export_api._queue_docx_export(
        ExportContext(tmp_path),
        {
            "scope": "selected_pages",
            "name": "selection",
            "selected": [
                {"batch": "first", "page_ids": ["page-2", "page-40"]},
                {"batch": "second", "page_ids": ["page-3"]},
            ],
        },
    )
    task.future.result(timeout=20)

    assert task.state == "done"
    assert task.done == task.total == 3
    with zipfile.ZipFile(task.result_path) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert "text 1" in document_xml
    assert "text 39" in document_xml
    assert "text 2" in document_xml
    assert "text 0" not in document_xml
