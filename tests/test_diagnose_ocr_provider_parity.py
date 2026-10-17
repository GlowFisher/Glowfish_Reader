import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bench" / "diagnose_ocr_provider_parity.py"
SPEC = importlib.util.spec_from_file_location("diagnose_ocr_provider_parity", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _page(lines):
    return {"lines": lines}


def test_diagnosis_distinguishes_recognition_from_line_count_differences():
    report = MODULE.diagnose(
        {
            "001": _page([{"text": "甲", "box": [1, 2, 3, 4]}]),
            "002": _page([{"text": "乙", "box": [1, 2, 3, 4]}]),
        },
        {
            "001": _page([{"text": "乙", "box": [1, 2, 3, 4]}]),
            "002": _page([{"text": "乙", "box": [1, 2, 3, 4]}, {"text": "丙", "box": [5, 6, 7, 8]}]),
        },
    )

    assert [page["kind"] for page in report["pages"]] == ["recognition_only", "line_count_changed"]
