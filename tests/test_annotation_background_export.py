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


def _write_annotated_document(work: Path, batch: str, page_count: int):
    directory = work / batch
    directory.mkdir()
    pages = []
    for index in range(page_count):
        line = {
            "id": f"line-{index}",
            "text": f"quoted text {index}",
            "annot": f"line annotation {index}",
        }
        pages.append({
            "page_id": f"page-{index + 1}",
            "page_annot": f"page annotation {index}",
            "lines": [line],
            "order": [line["id"]],
        })
    proof = {
        "batch": batch,
        "source": f"{batch}.pdf",
        "notes": "document annotation",
        "pages": pages,
    }
    (directory / "proof.json").write_text(json.dumps(proof), encoding="utf-8")


def test_annotation_task_streams_2000_pages_without_load_full(tmp_path, monkeypatch):
    _write_annotated_document(tmp_path, "annotations", 2000)
    manager = DocumentTaskManager(max_workers=1)
    monkeypatch.setattr(export_api, "TASK_MANAGER", manager)

    def reject_full_load(_self):
        raise AssertionError("annotation export must not load a complete document")

    monkeypatch.setattr(document_repository.DocumentRepository, "load_full", reject_full_load)
    task = export_api._queue_annotation_export(
        ExportContext(tmp_path),
        {"batches": ["annotations"], "name": "annotations"},
        "txt",
    )
    task.future.result(timeout=30)

    assert task.state == "done", task.error
    assert task.done == task.total == 2000
    output = task.result_path.read_text(encoding="utf-8")
    assert "document annotation" in output
    assert "line annotation 0" in output
    assert "line annotation 1999" in output


def test_annotation_docx_task_produces_valid_document(tmp_path, monkeypatch):
    _write_annotated_document(tmp_path, "docx annotations", 46)
    manager = DocumentTaskManager(max_workers=1)
    monkeypatch.setattr(export_api, "TASK_MANAGER", manager)
    task = export_api._queue_annotation_export(
        ExportContext(tmp_path),
        {"batches": ["docx annotations"], "name": "notes"},
        "docx",
    )
    task.future.result(timeout=20)

    assert task.state == "done", task.error
    with zipfile.ZipFile(task.result_path) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert "line annotation 0" in document_xml
    assert "line annotation 45" in document_xml
