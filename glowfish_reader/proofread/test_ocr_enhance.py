# -*- coding: utf-8 -*-
"""满血档后处理增强层的安全边界。

这些测试锁的都是「宁可不改，也不能把对的字改错/改丢」——搬迁同事分支时踩到的正是这类坑。
"""
import pytest
from PIL import Image

import ocr_enhance as E


class _Crop:
    """记录 predict_crop 收到什么、返回预设的识别行。"""

    def __init__(self, lines_per_call):
        self.lines_per_call = list(lines_per_call)
        self.calls = 0

    def __call__(self, path, size):
        self.calls += 1
        idx = min(self.calls - 1, len(self.lines_per_call) - 1)
        return self.lines_per_call[idx]


def _page():
    return Image.new("RGB", (400, 600), (255, 255, 255))


# ── 低分预过滤 ───────────────────────────────────────────────────────────────

def test_prefilter_is_off_by_default(monkeypatch):
    """默认不删行：它是满血档独有的减法，会让满血召回低于轻量，且消融 ΔF1=0。"""
    monkeypatch.delenv("GF_HIGH_MINSCORE", raising=False)
    lines = [{"text": "淡墨", "score": 0.30}, {"text": "清晰", "score": 0.95}]
    assert E.prefilter_by_score(lines) == lines


def test_prefilter_still_available_as_a_knob(monkeypatch):
    monkeypatch.setenv("GF_HIGH_MINSCORE", "0.55")
    lines = [{"text": "淡墨", "score": 0.30}, {"text": "清晰", "score": 0.95}]
    assert [l["text"] for l in E.prefilter_by_score(lines)] == ["清晰"]


def test_min_score_accepts_off_like_the_other_switches(monkeypatch):
    """GF_HIGH_MINSCORE=off 不许把 import 炸掉——另外四个开关都收 off/false/0。"""
    monkeypatch.setenv("GF_HIGH_MINSCORE", "off")
    assert E._min_line_score() == 0.0


def test_min_score_garbage_falls_back_instead_of_crashing(monkeypatch):
    monkeypatch.setenv("GF_HIGH_MINSCORE", "不是数字")
    assert E._min_line_score() == E.MIN_LINE_SCORE_DEFAULT


# ── 小字超分 ─────────────────────────────────────────────────────────────────

def test_small_text_rescue_never_shortens_text(monkeypatch):
    """放大后检测器把短列切碎，单字段置信度天然更高——不许拿「壹」换掉「壹佰兩」。"""
    monkeypatch.setenv("GF_HIGH_SMALLSR", "1")
    lines = [{"text": "壹佰兩", "box": [10, 10, 25, 60], "score": 0.80}]
    crop = _Crop([[{"text": "壹", "score": 0.93}]])
    E.rescue_small_text(crop, lines, _page(), None, "p001")
    assert lines[0]["text"] == "壹佰兩"
    assert "small_rescue" not in lines[0]


def test_small_text_rescue_skips_ambiguous_multi_line_result(monkeypatch):
    monkeypatch.setenv("GF_HIGH_SMALLSR", "1")
    lines = [{"text": "壹佰兩", "box": [10, 10, 25, 60], "score": 0.80}]
    crop = _Crop([[{"text": "壹佰兩肆", "score": 0.99}, {"text": "餘", "score": 0.95}]])
    E.rescue_small_text(crop, lines, _page(), None, "p001")
    assert lines[0]["text"] == "壹佰兩"


def test_small_text_rescue_accepts_longer_result(monkeypatch, tmp_path):
    monkeypatch.setenv("GF_HIGH_SMALLSR", "1")
    lines = [{"text": "壹佰", "box": [10, 10, 25, 60], "score": 0.60}]
    crop = _Crop([[{"text": "壹佰兩", "score": 0.88}]])
    E.rescue_small_text(crop, lines, _page(), tmp_path, "p001")
    assert lines[0]["text"] == "壹佰兩"
    assert lines[0]["small_rescue"] is True


# ── 多预处理集成 ─────────────────────────────────────────────────────────────

def test_ensemble_requires_real_score_margin_not_agreement(monkeypatch, tmp_path):
    """三个变体一起认错时一致率仍接近 1.0；替换判据必须用同量纲的 rec 分 + 余量。

    真实案例（s04_p1）：原行 0.792，三变体 0.742/0.742/0.799，均值 0.761 < 0.792+0.05，
    故不得替换。原实现拿一致率 0.953 去比，几乎必然替换，把对的字改错。
    """
    monkeypatch.setenv("GF_HIGH_ENSEMBLE", "1")
    lines = [{"text": "聖壽寺駐特僧佛", "box": [10, 10, 60, 400], "score": 0.792}]
    crop = _Crop([
        [{"text": "聖壽寺駐持僧備", "score": 0.742}],
        [{"text": "聖壽孝駐特僧位", "score": 0.742}],
        [{"text": "聖壽孝駐持僧併", "score": 0.799}],
    ])
    E.enhance_low_confidence_lines(crop, lines, _page(), tmp_path, "p001")
    assert lines[0]["text"] == "聖壽寺駐特僧佛"
    assert "ensemble_sources" not in lines[0]


def test_ensemble_replaces_when_variants_are_genuinely_better(monkeypatch, tmp_path):
    monkeypatch.setenv("GF_HIGH_ENSEMBLE", "1")
    lines = [{"text": "模糊一行", "box": [10, 10, 60, 400], "score": 0.60}]
    crop = _Crop([
        [{"text": "清晰一行", "score": 0.95}],
        [{"text": "清晰一行", "score": 0.93}],
        [{"text": "清晰一行", "score": 0.94}],
    ])
    E.enhance_low_confidence_lines(crop, lines, _page(), tmp_path, "p001")
    assert lines[0]["text"] == "清晰一行"
    assert lines[0]["ensemble_sources"] == list(E._PREPROCESS_NAMES)


def test_ensemble_ignores_multi_line_crop_results(monkeypatch, tmp_path):
    """裁剪图被切成多行时不知道哪行对应原行；只取 lines[0] 会用片段替换整行。"""
    monkeypatch.setenv("GF_HIGH_ENSEMBLE", "1")
    lines = [{"text": "原本一整列的文字", "box": [10, 10, 60, 400], "score": 0.60}]
    crop = _Crop([[{"text": "原本", "score": 0.99}, {"text": "一整列的文字", "score": 0.97}]] * 3)
    E.enhance_low_confidence_lines(crop, lines, _page(), tmp_path, "p001")
    assert lines[0]["text"] == "原本一整列的文字"


def test_preprocess_enhanced_reuses_shared_helper():
    """别再抄一份增强链——参数漂移只会体现在识别质量上，不会报错。"""
    import ocr_rescue
    img = Image.new("RGB", (40, 80), (128, 128, 128))
    assert E._preprocess_enhanced(img).tobytes() == ocr_rescue.enhance_for_ocr(img).tobytes()
