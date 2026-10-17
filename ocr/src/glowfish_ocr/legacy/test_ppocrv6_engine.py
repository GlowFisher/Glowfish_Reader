# -*- coding: utf-8 -*-
import json
import types
from pathlib import Path

from PIL import Image

import appconfig
import engines
import ocr_rescue
import recognize_ppocrv6 as r


class FakePPOCRv6:
    def __init__(self):
        self.calls = 0

    # 真 PaddleOCR.predict 收 text_det_* 逐调用覆盖（det_scale 按列距自适应用它），替身须同签名
    def predict(self, path, **det):
        self.calls += 1
        return [types.SimpleNamespace(json={"res": {
            "rec_texts": ["\u6b63\u6587\u7532", "\u6b63\u6587\u4e59"],
            "rec_scores": [0.93, 0.81],
            "rec_polys": [
                [[0, 0], [10, 0], [10, 20], [0, 20]],
                [20, 30, 40, 50],
            ],
        }})]


class FakePathAwarePPOCRv6:
    def __init__(self, by_name):
        self.by_name = by_name
        self.calls = []
        self.det_kwargs = []

    def predict(self, path, **det):
        name = Path(path).name
        self.calls.append(name)
        self.det_kwargs.append(det)
        rows = self.by_name.get(name, [])
        return [types.SimpleNamespace(json={"res": {
            "rec_texts": [row["text"] for row in rows],
            "rec_scores": [row.get("score", 0.9) for row in rows],
            "rec_polys": [row["box"] for row in rows],
        }})]


def _img(path, w=160, h=120):
    Image.new("RGB", (w, h), (255, 255, 255)).save(path)
    return path


def test_ppocrv6_registered_and_default():
    assert "ppocrv6" in engines.ENGINES
    assert "ppocrv6_onnx_high" in engines.ENGINES
    assert engines.DEFAULT_ENGINE == "ppocrv6_onnx_high"
    assert appconfig.DEFAULTS["engine"] == "ppocrv6"
    assert engines.engine_name(None) == "ppocrv6_onnx_high"


def test_paddle_high_engine_is_gone():
    """老满血档 ppocrv6_high 已作废删除，只剩一个满血档。"""
    assert "ppocrv6_high" not in engines.ENGINES
    assert not hasattr(engines, "PADDLE_HIGH_ENGINE")
    assert engines.engine_name("ppocrv6_high") == engines.DEFAULT_ENGINE   # 老配置自动落到新满血档


def test_resolve_ppocrv6_uses_paddle_python(monkeypatch):
    fake_py = r"C:\paddle\python.exe"
    monkeypatch.setattr(appconfig, "get_paddle_python", lambda: fake_py)
    name, prefix, params = engines.resolve_engine("ppocrv6")
    assert name == "ppocrv6"
    assert prefix == [fake_py, str(Path(engines.HERE) / "recognize_ppocrv6.py")]
    assert params["ocr_version"] == "PP-OCRv6"


def test_resolve_onnx_high_uses_high_accuracy_profile():
    name, prefix, params = engines.resolve_engine("ppocrv6_onnx_high")

    assert name == "ppocrv6_onnx_high"
    assert prefix[1].endswith("recognize_ppocrv6_onnx.py")
    assert params["ocr_version"] == "PP-OCRv6"
    assert params["column_rescue"] is True      # high-accuracy preset enables column rescue
    assert params["profile"] == "high_accuracy"
    assert params["text_det_box_thresh"] == 0.45


def test_build_engine_disables_textline_orientation_by_default(monkeypatch):
    captured = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(__import__("sys").modules, "paddleocr", types.SimpleNamespace(PaddleOCR=FakePaddleOCR))
    monkeypatch.setattr(r, "_ensure_paddlex_env", lambda: None)

    r._build_engine({"ocr_version": "PP-OCRv6", "lang": "chinese_cht"})

    assert captured["use_textline_orientation"] is False


def test_extract_ppocrv6_result():
    res = types.SimpleNamespace(json={"res": {
        "rec_texts": ["sample"],
        "rec_scores": [0.7],
        "rec_polys": [[[1, 2], [3, 2], [3, 4], [1, 4]]],
    }})
    texts, scores, polys = r.extract(res)
    assert texts == ["sample"]
    assert scores == [0.7]
    assert polys == [[[1, 2], [3, 2], [3, 4], [1, 4]]]


def test_recognize_one_writes_project_contract(tmp_path):
    img = _img(tmp_path / "p001.png")
    norm = tmp_path / "_img"
    norm.mkdir()

    out = r.recognize_one(FakePPOCRv6(), img, norm)

    assert (norm / "p001.jpg").is_file()
    assert out["width"] == 160 and out["height"] == 120
    assert out["ocr_meta"]["backend"] == "ppocrv6"
    assert out["ocr_meta"]["runtime"] == "paddle_static"
    assert out["ocr_meta"]["det_model"] == "PP-OCRv6_medium_det"
    assert out["ocr_meta"]["rec_model"] == "PP-OCRv6_medium_rec"
    assert out["lines"] == [
        {"text": "\u6b63\u6587\u7532", "box": [0.0, 0.0, 10.0, 20.0], "score": 0.93, "source": "full_page", "filter_status": "main_text", "filter_reason": ""},
        {"text": "\u6b63\u6587\u4e59", "box": [20.0, 30.0, 40.0, 50.0], "score": 0.81, "source": "full_page", "filter_status": "main_text", "filter_reason": ""},
    ]


def test_run_job_writes_recog_json(tmp_path):
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    _img(imgs / "a.png", 80, 60)
    out = tmp_path / "out" / "_recog.json"

    pages, failed = r.run_job(FakePPOCRv6(), imgs, out, log=lambda *a: None)

    assert pages == 1 and failed == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["a"]["lines"][0]["text"] == "\u6b63\u6587\u7532"
    assert (out.parent / "_img" / "a.jpg").is_file()


def test_recognize_one_marks_noise_without_dropping_it(tmp_path):
    img = _img(tmp_path / "p001.png", 800, 1000)
    norm = tmp_path / "_img"
    norm.mkdir()
    engine = FakePathAwarePPOCRv6({
        "p001_ocr.jpg": [
            {"text": "Scanned by CamScanner", "box": [80, 20, 620, 55], "score": 0.99},
            {"text": "\u6b63\u6587\u6b63\u6587\u6b63\u6587", "box": [610, 120, 680, 880], "score": 0.97},
        ]
    })

    out = r.recognize_one(engine, img, norm)

    assert [line["text"] for line in out["lines"]] == ["Scanned by CamScanner", "\u6b63\u6587\u6b63\u6587\u6b63\u6587"]
    assert out["lines"][0]["filter_status"] == "noise"
    assert out["lines"][0]["filter_reason"] == "watermark"
    assert out["lines"][1]["filter_status"] == "main_text"


def test_recognize_one_uses_column_rescue_by_default(monkeypatch, tmp_path):
    img = _img(tmp_path / "p001.png", 400, 600)
    norm = tmp_path / "_img"
    norm.mkdir()
    engine = FakePathAwarePPOCRv6({
        "p001_ocr.jpg": [],
        "p001_col_000.jpg": [{"text": "\u6551\u56de\u6b63\u6587", "box": [10, 20, 50, 220], "score": 0.92}],
    })
    monkeypatch.setattr(r.ocr_rescue, "find_vertical_text_columns", lambda image: [(300, 100, 370, 500)])

    out = r.recognize_one(engine, img, norm)

    assert "p001_col_000.jpg" in engine.calls
    assert out["lines"] == [{
        "text": "\u6551\u56de\u6b63\u6587",
        "box": [310.0, 120.0, 350.0, 320.0],
        "score": 0.92,
        "source": "column_rescue",
        "filter_status": "main_text",
        "filter_reason": "",
    }]


def test_recognize_one_can_disable_column_rescue(monkeypatch, tmp_path):
    img = _img(tmp_path / "p001.png", 400, 600)
    norm = tmp_path / "_img"
    norm.mkdir()
    engine = FakePathAwarePPOCRv6({
        "p001_ocr.jpg": [],
        "p001_col_000.jpg": [{"text": "\u6551\u56de\u6b63\u6587", "box": [10, 20, 50, 220], "score": 0.92}],
    })
    monkeypatch.setattr(r.ocr_rescue, "find_vertical_text_columns", lambda image: [(300, 100, 370, 500)])

    out = r.recognize_one(engine, img, norm, column_rescue=False)

    assert engine.calls == ["p001_ocr.jpg"]
    assert out["lines"] == []
    assert out["ocr_meta"]["rescued_columns"] == 0


def test_recognize_one_can_use_column_rescue_when_requested(monkeypatch, tmp_path):
    img = _img(tmp_path / "p001.png", 400, 600)
    norm = tmp_path / "_img"
    norm.mkdir()
    engine = FakePathAwarePPOCRv6({
        "p001_ocr.jpg": [],
        "p001_col_000.jpg": [{"text": "\u6551\u56de\u6b63\u6587", "box": [10, 20, 50, 220], "score": 0.92}],
    })
    monkeypatch.setattr(r.ocr_rescue, "find_vertical_text_columns", lambda image: [(300, 100, 370, 500)])

    out = r.recognize_one(engine, img, norm, column_rescue=True)

    assert "p001_col_000.jpg" in engine.calls
    assert out["lines"] == [{
        "text": "\u6551\u56de\u6b63\u6587",
        "box": [310.0, 120.0, 350.0, 320.0],
        "score": 0.92,
        "source": "column_rescue",
        "filter_status": "main_text",
        "filter_reason": "",
    }]


def test_dedupe_prefers_column_rescue_for_overlapping_vertical_column():
    lines = [
        {"text": "full_page_column_text", "box": [900, 555, 987, 1272], "score": 0.8333, "source": "full_page"},
        {"text": "better_column_text", "box": [904, 560, 984, 1270], "score": 0.8479, "source": "column_rescue"},
    ]

    kept = ocr_rescue.dedupe_lines(lines)

    assert kept == [lines[1]]


def test_dedupe_keeps_distinct_vertical_columns():
    lines = [
        {"text": "right_column", "box": [900, 100, 960, 700], "score": 0.9, "source": "full_page"},
        {"text": "left_column", "box": [760, 100, 820, 700], "score": 0.9, "source": "column_rescue"},
    ]

    kept = ocr_rescue.dedupe_lines(lines)

    assert kept == lines


def test_dedupe_keeps_footer_and_side_catalog_near_body_column():
    lines = [
        {"text": "archive_footer", "box": [1135, 1271, 1162, 1477], "score": 0.99, "source": "full_page"},
        {"text": "page_marker", "box": [1131, 1548, 1167, 1600], "score": 0.97, "source": "full_page"},
        {"text": "1-1-70-3", "box": [216, 1310, 331, 1340], "score": 0.99, "source": "full_page"},
    ]

    kept = ocr_rescue.dedupe_lines(lines)

    assert kept == lines


def test_dedupe_does_not_remove_manual_region_results():
    lines = [
        {"text": "manual_old", "box": [992, 662, 1053, 774], "score": 0.66, "source": "full_page"},
        {"text": "manual_new", "box": [997, 660, 1055, 778], "score": 0.72, "source": "manual_region"},
    ]

    kept = ocr_rescue.dedupe_lines(lines)

    assert kept == lines


def test_dedupe_high_accuracy_prefers_better_overlapping_candidate():
    lines = [
        {"text": "\u65e7\u5217", "box": [900, 100, 960, 700], "score": 0.93, "source": "full_enhanced"},
        {"text": "\u66f4\u5b8c\u6574\u7684\u6b63\u6587\u5217", "box": [902, 105, 962, 705], "score": 0.89, "source": "column_wide_rescue"},
    ]

    kept, stats = ocr_rescue.merge_high_accuracy_lines(lines)

    assert kept == [lines[1]]
    assert stats["duplicates_removed"] == 1


def test_dedupe_high_accuracy_rejects_garbage_even_when_longer():
    good = {"text": "\u7acb\u5951\u7d04\u4eba\u9858\u5c07\u571f\u5730", "box": [900, 100, 960, 700], "score": 0.9, "source": "full_enhanced"}
    garbage = {"text": "\u623f\u52a1\u5802\u5e02" * 12, "box": [902, 105, 962, 705], "score": 0.51, "source": "column_wide_rescue"}

    kept, stats = ocr_rescue.merge_high_accuracy_lines([good, garbage])

    assert kept == [good]
    assert stats["duplicates_removed"] == 1


class BoomPPOCRv6:
    """整页识别抛异常的替身（GPU OOM / det 崩）。"""

    def predict(self, path, **det):
        raise RuntimeError("det crashed")


def test_baseline_profile_page_failure_still_reported(tmp_path):
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    _img(imgs / "a.png", 800, 1000)
    out = tmp_path / "out" / "_recog.json"

    pages, failed = r.run_job(BoomPPOCRv6(), imgs, out, log=lambda *a: None, config={})

    assert (pages, failed) == (1, 1)
