import json

import document_repository
import library_api


def _write_source(directory, page_count):
    directory.mkdir()
    source_images = directory / "_src"
    source_images.mkdir()
    pages = []
    for index in range(page_count):
        image = source_images / f"page-{index + 1}.png"
        image.write_bytes(b"image")
        pages.append({
            "page_id": f"page-{index + 1}",
            "image": str(image.resolve()),
            "lines": [{"id": f"line-{index}", "text": f"text {index}"}],
            "order": [f"line-{index}"],
        })
    proof = {
        "batch": directory.name,
        "image_dir": str(source_images.resolve()),
        "pages": pages,
    }
    (directory / "proof.json").write_text(json.dumps(proof), encoding="utf-8")


def test_copy_rebases_page_files_without_full_document_load(tmp_path, monkeypatch):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    _write_source(source, 100)

    def reject_full_load(_self):
        raise AssertionError("document copy must not load the complete document")

    monkeypatch.setattr(document_repository.DocumentRepository, "load_full", reject_full_load)
    meta = library_api._copy_page_repository(source, destination, "destination")

    assert meta["batch"] == "destination"
    assert len(meta["pages"]) == 100
    repo = document_repository.DocumentRepository(destination)
    first = repo.load_page("page-1")["page"]
    last = repo.load_page("page-100")["page"]
    assert str(destination.resolve()) in first["image"]
    assert str(destination.resolve()) in last["image"]
    assert str(source.resolve()) not in first["image"]


def test_failed_copy_removes_incomplete_destination(tmp_path, monkeypatch):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    _write_source(source, 3)

    def fail_meta(_self):
        raise OSError("simulated metadata failure")

    monkeypatch.setattr(document_repository.DocumentRepository, "load_meta", fail_meta)
    try:
        library_api._copy_page_repository(source, destination, "destination")
    except OSError:
        pass
    else:
        raise AssertionError("copy failure was not propagated")
    assert not destination.exists()
