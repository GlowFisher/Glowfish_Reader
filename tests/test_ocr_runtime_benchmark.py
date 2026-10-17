import json
import sys
from pathlib import Path


PROOFREAD = Path(__file__).resolve().parents[1] / "glowfish_reader" / "proofread"
sys.path.insert(0, str(PROOFREAD))
from ocr_runtime_benchmark import _result_summary  # noqa: E402


def _write_result(path: Path, image: str, text: str = "same"):
    path.write_text(
        json.dumps(
            {
                "page": {
                    "image": image,
                    "width": 10,
                    "height": 20,
                    "lines": [{"text": text, "score": 0.9}],
                    "ocr_meta": {"backend": "onnx"},
                },
                "_meta": {"engine": "ppocrv6_onnx_high"},
            }
        ),
        encoding="utf-8",
    )


def test_result_fingerprint_ignores_temp_directory_and_top_level_cache_meta(tmp_path):
    legacy = tmp_path / "legacy.json"
    component = tmp_path / "component.json"
    _write_result(legacy, r"C:\legacy-temp\norm\page.jpg")
    _write_result(component, r"D:\component-temp\norm\page.jpg")

    assert _result_summary(legacy) == _result_summary(component)


def test_result_fingerprint_retains_recognized_content(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write_result(first, "page.jpg", text="first")
    _write_result(second, "page.jpg", text="second")

    assert _result_summary(first)[0] != _result_summary(second)[0]


def test_result_fingerprint_ignores_provider_identity_and_page_timing(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write_result(first, "page.jpg")
    _write_result(second, "page.jpg")
    payload = json.loads(second.read_text(encoding="utf-8"))
    payload["page"]["ocr_meta"].update({
        "provider": "cuda", "device": "gpu:0", "runtime_version": "candidate",
        "stage_timings_ms": {"page_total": 123.45}, "attempt": 2,
    })
    second.write_text(json.dumps(payload), encoding="utf-8")

    assert _result_summary(first) == _result_summary(second)
