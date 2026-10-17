import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bench" / "compare_ocr_gold_corpus.py"
SPEC = importlib.util.spec_from_file_location("compare_ocr_gold_corpus", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _page(text, box, provider):
    return {"lines": [{"text": text, "box": box}], "ocr_meta": {"provider": provider}}


def test_compare_separates_provider_parity_from_gold_accuracy():
    report = MODULE.compare(
        {"001": _page("甲乙", [1, 2, 3, 4], "cpu")},
        {"001": _page("甲乙", [1, 2, 3, 4], "cuda")},
        {"001": "甲 乙"},
    )

    assert report["summary"]["text_exact_pages"] == 1
    assert report["summary"]["geometry_exact_pages"] == 1
    assert report["summary"]["cpu_gold_cer"] == 0
    assert report["summary"]["cuda_gold_cer"] == 0
