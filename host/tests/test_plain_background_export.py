import json
import zipfile
from pathlib import Path

import export_api
from document_task_manager import DocumentTaskManager


class ExportContext:
    def __init__(self, work):
        self.uid = "test-user"
        self.work = work

    def reg(self, batch):
        proof = self.work / batch / "proof.json"
        return {"proof_path": str(proof)} if proof.is_file() else None


def _write_proof(work: Path, batch: str, page_count: int, *, images=False, annotations=False):
    directory = work / batch
    directory.mkdir(parents=True)
    if images:
        (directory / "_src").mkdir()
    pages = []
    for index in range(page_count):
        image_name = f"page-{index + 1}.png"
        if images:
            (directory / "_src" / image_name).write_bytes(f"image-{index}".encode())
        line = {"id": f"line-{index}", "text": f"text {index}"}
        if annotations and index == 0:
            line["annot"] = "line note"
        pages.append({
            "page_id": f"page-{index + 1}",
            "image": image_name,
            "lines": [line],
            "order": [line["id"]],
        })
    proof = {"batch": batch, "notes": "document note" if annotations else "", "pages": pages}
    (directory / "proof.json").write_text(json.dumps(proof), encoding="utf-8")


def test_plain_export_with_images_writes_zip_on_disk(tmp_path, monkeypatch):
    _write_proof(tmp_path, "images", 46, images=True)
    monkeypatch.setattr(export_api.safefs, "within_work", lambda _path: True)
    manager = DocumentTaskManager(max_workers=1)
    monkeypatch.setattr(export_api, "TASK_MANAGER", manager)

    task = export_api._queue_plain_export(
        ExportContext(tmp_path),
        {"scope": "all", "batch": "images", "name": "images"},
        "txt",
        page_marks=True,
        with_images=True,
    )
    task.future.result(timeout=20)

    assert task.state == "done"
    assert task.done == task.total == 46
    with zipfile.ZipFile(task.result_path) as archive:
        names = archive.namelist()
        assert sum(name.endswith(".png") for name in names) == 46
        document = archive.read(next(name for name in names if name.endswith(".txt"))).decode("utf-8")
    assert "text 0" in document
    assert "text 45" in document


def test_annotated_plain_export_uses_background_page_iterator(tmp_path, monkeypatch):
    _write_proof(tmp_path, "annotated", 100, annotations=True)
    manager = DocumentTaskManager(max_workers=1)
    monkeypatch.setattr(export_api, "TASK_MANAGER", manager)

    task = export_api._queue_plain_export(
        ExportContext(tmp_path),
        {"scope": "all", "batch": "annotated", "name": "annotated"},
        "md",
        with_annotations=True,
    )
    task.future.result(timeout=20)

    assert task.state == "done"
    assert task.done == task.total == 100
    output = task.result_path.read_text(encoding="utf-8")
    assert "line note" in output
    assert "document note" in output
    assert "text 99" in output
