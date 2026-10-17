import json
import types

from PIL import Image

from glowfish_ocr.checkpoint import OcrCheckpoint
import recognize_ppocrv6 as worker


class FakeEngine:
    def __init__(self):
        self.calls = 0

    def predict(self, path, **_kwargs):
        self.calls += 1
        return [
            types.SimpleNamespace(
                json={
                    "res": {
                        "rec_texts": ["page"],
                        "rec_scores": [0.99],
                        "rec_polys": [[[0, 0], [10, 0], [10, 20], [0, 20]]],
                    }
                }
            )
        ]


def _image(path):
    Image.new("RGB", (80, 60), "white").save(path)
    return path


def test_host_worker_skips_pages_already_in_component_checkpoint(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    paths = [_image(images / f"p{index:03}.png") for index in range(1, 4)]
    checkpoint_dir = tmp_path / "_ocr_checkpoint"
    checkpoint = OcrCheckpoint(
        checkpoint_dir, paths, requested_engine="ppocrv6", job_id="first"
    )
    first_image = checkpoint.images_dir / "p001.jpg"
    first_image.write_bytes(b"normalized")
    checkpoint.record_success(
        "p001",
        {"image": str(first_image), "width": 80, "height": 60, "lines": []},
        engine="ppocrv6",
        attempt=1,
    )
    engine = FakeEngine()
    output = tmp_path / "job" / "recog.json"

    pages, failed = worker._run_checkpoint_job(
        engine,
        images,
        output,
        config={"column_rescue": False},
        checkpoint_dir=checkpoint_dir,
        job_id="resumed",
        attempt=2,
        log=lambda *_args: None,
    )

    assert pages == 3
    assert failed == 0
    assert engine.calls == 2
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert list(payload) == ["p001", "p002", "p003"]
    assert payload["p001"]["ocr_meta"]["attempt"] == 1
    assert payload["p002"]["ocr_meta"]["attempt"] == 2
