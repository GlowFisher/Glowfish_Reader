# -*- coding: utf-8 -*-
"""满血档（ppocrv6_onnx_high = ONNX + profile=high_accuracy）的流水线不变量。

老的 Paddle 满血档 ppocrv6_high 已作废删除，这里承接它原有的两条保障：
  ① 整页那一趟必须带 det 自适应尺度覆盖，否则大图退回原尺寸检测、整列漏检；
  ② 整页那一趟炸了 = 整页没识别，必须抛出去让 run_job 标 failed，不能吞成 0 行的「正常页」。
另加满血档特有的增强层开关语义。
"""
import json
from pathlib import Path

import pytest
from PIL import Image

import recognize_ppocrv6_onnx as o


def _img(path, w, h):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), (255, 255, 255)).save(path)
    return path


class FakeEngine:
    """记录每次 predict 的文件名与 det 覆盖参数。"""

    def __init__(self, by_name=None, boom_on=None):
        self.by_name = by_name or {}
        self.boom_on = boom_on
        self.calls = []
        self.det_kwargs = []

    def predict(self, path, **det):
        name = Path(path).name
        self.calls.append(name)
        self.det_kwargs.append(det)
        if self.boom_on and name == self.boom_on:
            raise RuntimeError("full page pass failed")
        lines = self.by_name.get(name, [])
        return [{"res": {"rec_texts": [l["text"] for l in lines],
                         "rec_scores": [l["score"] for l in lines],
                         "rec_boxes": [l["box"] for l in lines]}}]


@pytest.fixture(autouse=True)
def _no_adaptive_off(monkeypatch):
    monkeypatch.setattr(o, "EXPLICIT_DET_CFG", False)


def _quiet_enhance(monkeypatch):
    """关掉三层增强，隔离出「整页单趟 + det 自适应」这条主干。"""
    for var in ("GF_HIGH_LOWTHRESH", "GF_HIGH_ENSEMBLE", "GF_HIGH_SMALLSR", "GF_OCR_CONFUSION"):
        monkeypatch.setenv(var, "0")


def test_high_accuracy_full_page_pass_carries_adaptive_det(monkeypatch, tmp_path):
    """整页那一趟必须带自适应 det 尺度；这是整列漏检的根因修复，不是「增强」。"""
    _quiet_enhance(monkeypatch)
    img = _img(tmp_path / "p001.png", 4000, 6000)
    norm = tmp_path / "_img"
    norm.mkdir()
    engine = FakeEngine({"p001_ocr.jpg": [{"text": "整頁", "box": [10, 20, 50, 220], "score": 0.82}]})
    monkeypatch.setattr(o.ocr_rescue, "find_vertical_text_columns", lambda image: [(300, 100, 370, 500)])
    monkeypatch.setattr(o.ocr_rescue, "uncovered_columns", lambda cols, lines: [])
    monkeypatch.setattr(o.ocr_rescue, "is_low_recall", lambda lines, w, h: False)
    monkeypatch.setattr(o.ocr_rescue, "find_body_region", lambda image: (0, 0, 4000, 6000))

    out = o.recognize_one(engine, img, norm, profile="high_accuracy")

    assert engine.calls == ["p001_ocr.jpg"]
    assert engine.det_kwargs[0].get("text_det_limit_type") == "max"
    assert out["ocr_meta"]["profile"] == "high_accuracy"
    assert out["ocr_meta"]["det_adaptive"] is True


def test_high_accuracy_full_page_failure_raises(monkeypatch, tmp_path):
    """整页那一趟炸了必须抛出去。吞掉的话会返回 0 行的「正常页」，还会被写进缓存。"""
    _quiet_enhance(monkeypatch)
    img = _img(tmp_path / "p001.png", 800, 1000)
    norm = tmp_path / "_img"
    norm.mkdir()
    engine = FakeEngine({}, boom_on="p001_ocr.jpg")
    monkeypatch.setattr(o.ocr_rescue, "find_vertical_text_columns", lambda image: [])
    monkeypatch.setattr(o.ocr_rescue, "find_body_region", lambda image: (0, 0, 800, 1000))

    with pytest.raises(RuntimeError, match="full page pass failed"):
        o.recognize_one(engine, img, norm, profile="high_accuracy")


def test_high_accuracy_page_failure_is_reported_not_swallowed(monkeypatch, tmp_path):
    _quiet_enhance(monkeypatch)
    imgs = tmp_path / "imgs"
    _img(imgs / "a.png", 800, 1000)
    out = tmp_path / "out" / "_recog.json"
    engine = FakeEngine({}, boom_on="a_ocr.jpg")
    monkeypatch.setattr(o.ocr_rescue, "find_vertical_text_columns", lambda image: [])
    monkeypatch.setattr(o.ocr_rescue, "find_body_region", lambda image: (0, 0, 800, 1000))

    pages, failed = o.run_job(engine, imgs, out, log=lambda *a: None,
                              config={"profile": "high_accuracy"})

    assert (pages, failed) == (1, 1)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["a"]["failed"] is True
    assert data["a"]["lines"] == []


def test_lightweight_profile_has_no_high_accuracy_meta(monkeypatch, tmp_path):
    """轻量档不带 profile/merge_stats/det_adaptive——det 参数由引擎构造时定死。"""
    monkeypatch.setenv("GF_OCR_CONFUSION", "0")
    img = _img(tmp_path / "p001.png", 4000, 6000)
    norm = tmp_path / "_img"
    norm.mkdir()
    engine = FakeEngine({"p001_ocr.jpg": [{"text": "整頁", "box": [10, 20, 50, 220], "score": 0.9}]})
    monkeypatch.setattr(o.ocr_rescue, "find_vertical_text_columns", lambda image: [(300, 100, 370, 500)])
    monkeypatch.setattr(o.ocr_rescue, "uncovered_columns", lambda cols, lines: [])
    monkeypatch.setattr(o.ocr_rescue, "is_low_recall", lambda lines, w, h: False)
    monkeypatch.setattr(o.ocr_rescue, "find_body_region", lambda image: (0, 0, 4000, 6000))

    out = o.recognize_one(engine, img, norm, profile=None)

    assert "profile" not in out["ocr_meta"]
    # 轻量版 page_det 永为 None→det_adaptive=False；det 参数由 _build_engine 时定死。
    assert out["ocr_meta"]["det_adaptive"] is False
    assert out["ocr_meta"]["body_region"] == [0, 0, 4000, 6000]


def test_annotate_runs_after_enhancement_so_rescued_lines_are_reclassified(monkeypatch, tmp_path):
    """增强层改写 text/score 之后才可以分类。

    classify_line 同时看 text 和 score，而层② 专挑 score<0.85 的行提分——这些行最可能
    已被判成 low_conf_noise。先 annotate 的话，提分救回的行仍顶着 noise 身份被
    proof_model 从正文剔除，三趟推理白跑。
    """
    img = _img(tmp_path / "p001.png", 800, 1000)
    norm = tmp_path / "_img"
    norm.mkdir()
    engine = FakeEngine({"p001_ocr.jpg": [{"text": "壹貳參肆伍陸柒捌玖拾", "box": [100, 50, 140, 900], "score": 0.40}]})
    monkeypatch.setattr(o.ocr_rescue, "find_vertical_text_columns", lambda image: [])
    monkeypatch.setattr(o.ocr_rescue, "is_low_recall", lambda lines, w, h: False)
    monkeypatch.setattr(o.ocr_rescue, "find_body_region", lambda image: (0, 0, 800, 1000))
    monkeypatch.setenv("GF_HIGH_LOWTHRESH", "0")
    monkeypatch.setenv("GF_HIGH_SMALLSR", "0")
    monkeypatch.setenv("GF_OCR_CONFUSION", "0")

    # 集成层把这行从 0.40 提到 0.95：分类必须看到提升后的分数。
    def fake_enhance(predict_crop, lines, oriented, norm_dir, pid):
        for line in lines:
            line["score"] = 0.95
        return lines

    monkeypatch.setattr(o.ocr_enhance, "enhance_low_confidence_lines", fake_enhance)
    seen_scores = []

    real_annotate = o.ocr_filter.annotate_page_lines

    def spy(lines, w, h, image_path=None):
        seen_scores.extend((l.get("score") or 0) for l in lines)
        return real_annotate(lines, w, h, image_path=image_path)

    monkeypatch.setattr(o.ocr_filter, "annotate_page_lines", spy)
    o.recognize_one(engine, img, norm, profile="high_accuracy")

    assert seen_scores == [0.95], f"annotate 看到的是提分前的分数：{seen_scores}"


def test_low_threshold_second_pass_is_off_by_default(monkeypatch, tmp_path):
    """层⑤默认关：竖排页上判据几乎恒真，多跑一整趟整页推理而 ΔF1=0.000。"""
    monkeypatch.delenv("GF_HIGH_LOWTHRESH", raising=False)
    assert o.ocr_enhance.low_thresh_enabled() is False
    monkeypatch.setenv("GF_HIGH_LOWTHRESH", "1")
    assert o.ocr_enhance.low_thresh_enabled() is True
