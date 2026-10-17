import json

import pytest

from glowfish_ocr.checkpoint import CheckpointMismatch, OcrCheckpoint


def _images(tmp_path, count=3):
    root = tmp_path / "source"
    root.mkdir()
    images = []
    for index in range(count):
        path = root / f"p{index + 1:03}.png"
        path.write_bytes(f"page-{index}".encode())
        images.append(path)
    return images


def _page(image):
    return {"image": str(image), "width": 10, "height": 20, "lines": []}


def test_checkpoint_resumes_only_successful_pages(tmp_path):
    images = _images(tmp_path)
    root = tmp_path / "checkpoint"
    first = OcrCheckpoint(
        root, images, requested_engine="ppocrv6_onnx_high", job_id="job-1"
    )
    normalized = first.images_dir / "p001.jpg"
    normalized.write_bytes(b"normalized")
    first.record_success("p001", _page(normalized), engine="ppocrv6_onnx_high", attempt=1)
    first.record_failure("p002", RuntimeError("boom"), engine="ppocrv6_onnx_high", attempt=1)

    resumed = OcrCheckpoint(
        root, images, requested_engine="ppocrv6_onnx_high", job_id="job-2", attempt=2
    )

    assert list(resumed.load_pages()) == ["p001"]
    assert resumed.progress()["done"] == 1
    assert resumed.progress()["failed"] == ["p002"]
    assert resumed.progress()["completed_by_engine"] == {"ppocrv6_onnx_high": 1}
    page = resumed.load_pages()["p001"]
    assert page["ocr_meta"] == {"engine": "ppocrv6_onnx_high", "attempt": 1}


def test_checkpoint_rejects_changed_source(tmp_path):
    images = _images(tmp_path)
    root = tmp_path / "checkpoint"
    OcrCheckpoint(root, images, requested_engine="ppocrv6")
    images[0].write_bytes(b"changed")

    with pytest.raises(CheckpointMismatch, match="source fingerprint"):
        OcrCheckpoint(root, images, requested_engine="ppocrv6")


def test_materialize_requires_all_pages_and_copies_images(tmp_path):
    images = _images(tmp_path, count=2)
    checkpoint = OcrCheckpoint(
        tmp_path / "checkpoint", images, requested_engine="ppocrv6"
    )
    for image in images:
        normalized = checkpoint.images_dir / f"{image.stem}.jpg"
        normalized.write_bytes(image.read_bytes())
        checkpoint.record_success(
            image.stem, _page(normalized), engine="ppocrv6", attempt=1
        )

    output = tmp_path / "job" / "recog.json"
    pages = checkpoint.materialize(output)

    assert list(pages) == ["p001", "p002"]
    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8")).keys() == pages.keys()
    assert (output.parent / "_img" / "p001.jpg").read_bytes() == b"page-0"
    manifest = json.loads(checkpoint.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"

def test_eight_hundred_page_job_resumes_at_multiple_interruptions(tmp_path):
    images = _images(tmp_path, count=800)
    root = tmp_path / "checkpoint"
    processed = []

    first = OcrCheckpoint(
        root, images, requested_engine="ppocrv6_onnx_high", job_id="first"
    )
    for image in images[:200]:
        first.record_success(
            image.stem, _page(image), engine="ppocrv6_onnx_high", attempt=1
        )
        processed.append(image.stem)

    second = OcrCheckpoint(
        root, images, requested_engine="ppocrv6_onnx_high", job_id="second", attempt=2
    )
    assert len(second.load_pages()) == 200
    for image in images[200:600]:
        second.record_success(
            image.stem, _page(image), engine="ppocrv6_onnx_high", attempt=2
        )
        processed.append(image.stem)

    fallback = OcrCheckpoint(
        root, images, requested_engine="ppocrv6_onnx", job_id="fallback", attempt=3
    )
    assert len(fallback.load_pages()) == 600
    for image in images[600:]:
        fallback.record_success(
            image.stem, _page(image), engine="ppocrv6_onnx", attempt=3
        )
        processed.append(image.stem)

    output = tmp_path / "final" / "recog.json"
    pages = fallback.materialize(output)

    assert len(processed) == len(set(processed)) == 800
    assert len(pages) == 800
    assert fallback.progress()["completed_by_engine"] == {
        "ppocrv6_onnx_high": 600,
        "ppocrv6_onnx": 200,
    }
