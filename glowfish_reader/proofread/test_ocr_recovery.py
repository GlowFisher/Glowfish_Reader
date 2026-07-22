import json

import ocr_recovery


def _source(tmp_path):
    path = tmp_path / "upload" / "book.pdf"
    path.parent.mkdir()
    path.write_bytes(b"pdf")
    return [{"path": str(path), "type": "pdf", "page": 0}]


def test_recovery_record_is_discoverable_without_exposing_paths(tmp_path):
    work = tmp_path / "users" / "local"
    batch_dir = work / "book"
    (batch_dir / "_src").mkdir(parents=True)
    record = ocr_recovery.create_record(
        batch_dir,
        batch="book",
        source="Book",
        engine="ppocrv6_onnx_high",
        request_id="request-1",
        source_items=_source(tmp_path),
        total=3,
    )
    pages = batch_dir / "_ocr_checkpoint" / "pages"
    pages.mkdir()
    (pages / "p001.json").write_text(
        json.dumps({"lines": [], "ocr_meta": {"engine": "ppocrv6_onnx_high"}}),
        encoding="utf-8",
    )

    jobs = ocr_recovery.discover(work)

    assert len(jobs) == 1
    assert jobs[0]["job_id"] == record["job_id"]
    assert jobs[0]["completed"] == 1
    assert jobs[0]["total"] == 3
    assert jobs[0]["completed_by_engine"] == {"ppocrv6_onnx_high": 1}
    assert "path" not in jobs[0]
    assert ocr_recovery.find(work, record["job_id"])[0] == batch_dir


def test_completed_proof_is_not_recoverable(tmp_path):
    work = tmp_path / "work"
    batch_dir = work / "book"
    batch_dir.mkdir(parents=True)
    ocr_recovery.create_record(
        batch_dir,
        batch="book",
        source="Book",
        engine="ppocrv6",
        request_id="request-1",
        source_items=_source(tmp_path),
        total=1,
    )
    (batch_dir / "proof.json").write_text("{}", encoding="utf-8")

    assert ocr_recovery.discover(work) == []


def test_source_fingerprint_is_stable_and_sensitive_to_size(tmp_path):
    items = _source(tmp_path)
    first = ocr_recovery.source_fingerprint(items)
    assert first == ocr_recovery.source_fingerprint(items)

    with open(items[0]["path"], "ab") as stream:
        stream.write(b"changed")
    assert first != ocr_recovery.source_fingerprint(items)


def test_frozen_build_includes_recovery_modules():
    spec = (
        __import__("pathlib").Path(__file__).with_name("glowfish_reader.spec")
        .read_text(encoding="utf-8")
    )
    assert '"glowfish_ocr.checkpoint"' in spec
    assert '"ocr_recovery"' in spec
