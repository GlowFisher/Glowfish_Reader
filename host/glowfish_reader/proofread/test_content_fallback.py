# -*- coding: utf-8 -*-
import json
from pathlib import Path
import content_api


class Ctx:
    def __init__(self, p):
        self.progress_path = p

    def read_progress(self):
        path = Path(self.progress_path)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_progress(self, data):
        Path(self.progress_path).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_ensure_recog_falls_back_to_ppocrv6_onnx(monkeypatch, tmp_path):
    calls = []

    def fake_run_engine(ctx, image_dir, recog_path, eng):
        calls.append(eng)
        if eng == "paddle":
            raise RuntimeError("vl boom")
        Path(recog_path).write_text('{"p001": {"lines": []}}', encoding="utf-8")  # ppocrv6_onnx 鎴愬姛

    monkeypatch.setattr(content_api, "_run_engine", fake_run_engine)
    out = tmp_path / "_recog.json"
    ctx = Ctx(str(tmp_path / "progress.json"))
    content_api._ensure_recog(ctx, tmp_path, out, engine="paddle")
    assert calls == ["paddle", "ppocrv6_onnx"]                       # 鍏?VL 鍚庡洖閫€ ppocrv6_onnx
    assert out.exists()
    prog = json.loads(Path(ctx.progress_path).read_text(encoding="utf-8"))
    assert prog.get("fallback", {}).get("from") == "paddle"


def test_ensure_recog_no_fallback_when_ppocrv6_onnx_fails(monkeypatch, tmp_path):
    def boom(ctx, image_dir, recog_path, eng):
        raise RuntimeError("ppocrv6_onnx boom")

    monkeypatch.setattr(content_api, "_run_engine", boom)
    out = tmp_path / "_recog.json"
    ctx = Ctx(str(tmp_path / "progress.json"))
    try:
        content_api._ensure_recog(ctx, tmp_path, out, engine="ppocrv6_onnx")
        assert False, "搴旀姏 HTTPException"
    except Exception as e:
        assert "Recognition failed" in str(getattr(e, "detail", e))


def test_finish_progress_preserves_fallback(tmp_path):
    ctx = Ctx(str(tmp_path / "progress.json"))
    ctx.write_progress({"phase": "done", "fallback": {"from": "paddle", "to": "ppocrv6_onnx"}})
    content_api._finish_progress(ctx)
    prog = ctx.read_progress()
    assert prog["phase"] == "done"
    assert prog["done"] == 1
    assert prog["fallback"]["from"] == "paddle"



def test_begin_ocr_progress_marks_recognition_stage(tmp_path):
    src = tmp_path / "_src"
    src.mkdir()
    (src / "p001.jpg").write_bytes(b"x")
    ctx = Ctx(str(tmp_path / "progress.json"))

    content_api._begin_ocr_progress(ctx, src, "ppocrv6")

    prog = ctx.read_progress()
    assert prog["phase"] == "ocr"
    assert prog["done"] == 0
    assert prog["total"] == 1
    assert prog["engine"] == "ppocrv6"

def test_ppocrv6_low_recall_uses_ppocrv6_onnx_when_better(monkeypatch, tmp_path):
    calls = []

    def fake_run_engine(ctx, image_dir, recog_path, eng):
        calls.append(eng)
        if eng == "ppocrv6":
            Path(recog_path).write_text(
                json.dumps({"p001": {"width": 800, "height": 1000, "lines": []}}, ensure_ascii=False),
                encoding="utf-8")
        elif eng == "ppocrv6_onnx":
            lines = [{"text": "姝ｆ枃" * 80, "box": [600, 100, 680, 900], "score": 0.91}]
            Path(recog_path).write_text(
                json.dumps({"p001": {"width": 800, "height": 1000, "lines": lines}}, ensure_ascii=False),
                encoding="utf-8")

    monkeypatch.setattr(content_api, "_run_engine", fake_run_engine)
    out = tmp_path / "_recog.json"
    ctx = Ctx(str(tmp_path / "progress.json"))

    actual = content_api._ensure_recog(ctx, tmp_path, out, engine="ppocrv6")

    assert actual == "ppocrv6_onnx"
    assert calls == ["ppocrv6", "ppocrv6_onnx"]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["p001"]["lines"][0]["text"].startswith("姝ｆ枃")
    prog = json.loads(Path(ctx.progress_path).read_text(encoding="utf-8"))
    assert prog["fallback"]["from"] == "ppocrv6"





def test_ppocrv6_garbage_columns_use_ppocrv6_onnx_when_better(monkeypatch, tmp_path):
    calls = []
    bad_text = "\u623f\u52a1\u5802\u5e02" * 12
    good_text = "\u7acb\u5951\u7d04\u4eba\u9858\u5c07\u571f\u5730\u623f\u5c4b\u51fa\u552e\u7d66\u8cb7\u65b9" * 6

    def fake_run_engine(ctx, image_dir, recog_path, eng):
        calls.append(eng)
        if eng == "ppocrv6":
            lines = [
                {"text": bad_text, "box": [610, 120, 680, 920], "score": 0.51, "filter_status": "main_text"},
                {"text": "\u5951\u7d04\u6458\u8981", "box": [500, 120, 560, 260], "score": 0.88, "filter_status": "main_text"},
            ]
        else:
            lines = [{"text": good_text, "box": [610, 120, 680, 920], "score": 0.93, "filter_status": "main_text"}]
        Path(recog_path).write_text(
            json.dumps({"p001": {"width": 1000, "height": 1400, "lines": lines}}, ensure_ascii=False),
            encoding="utf-8")

    monkeypatch.setattr(content_api, "_run_engine", fake_run_engine)
    monkeypatch.setattr(content_api.ocr_rescue, "is_low_recall", lambda lines, w, h: False)
    out = tmp_path / "_recog.json"
    ctx = Ctx(str(tmp_path / "progress.json"))

    actual = content_api._ensure_recog(ctx, tmp_path, out, engine="ppocrv6")

    assert actual == "ppocrv6_onnx"
    assert calls == ["ppocrv6", "ppocrv6_onnx"]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["p001"]["lines"][0]["text"] == good_text
    prog = ctx.read_progress()
    assert prog["fallback"]["reason"] == "native_ppocrv6_garbage_columns"


def test_ppocrv6_normal_quality_does_not_run_onnx(monkeypatch, tmp_path):
    calls = []
    text = "\u7acb\u5951\u7d04\u4eba\u9858\u5c07\u571f\u5730\u623f\u5c4b\u51fa\u552e\u7d66\u8cb7\u65b9" * 4

    def fake_run_engine(ctx, image_dir, recog_path, eng):
        calls.append(eng)
        lines = [{"text": text, "box": [610, 120, 680, 920], "score": 0.93, "filter_status": "main_text"}]
        Path(recog_path).write_text(
            json.dumps({"p001": {"width": 1000, "height": 1400, "lines": lines}}, ensure_ascii=False),
            encoding="utf-8")

    monkeypatch.setattr(content_api, "_run_engine", fake_run_engine)
    monkeypatch.setattr(content_api.ocr_rescue, "is_low_recall", lambda lines, w, h: False)
    out = tmp_path / "_recog.json"
    ctx = Ctx(str(tmp_path / "progress.json"))

    actual = content_api._ensure_recog(ctx, tmp_path, out, engine="ppocrv6")

    assert actual == "ppocrv6"
    assert calls == ["ppocrv6"]
def test_resolve_ppocrv6_params_enable_column_rescue(monkeypatch):
    fake_py = r"C:\paddle\python.exe"
    monkeypatch.setattr(content_api.engines.appconfig, "get_paddle_python", lambda: fake_py)

    name, prefix, params = content_api.engines.resolve_engine("ppocrv6")

    assert name == "ppocrv6"
    assert params["column_rescue"] is True


def test_worker_for_restarts_when_config_changes(monkeypatch):
    created = []

    class FakeWorker:
        def __init__(self, prefix, env=None, model_type="ppocrv6", config=None):
            self.prefix = list(prefix)
            self.env = env
            self.model_type = model_type
            self.config = dict(config or {})
            self.closed = False
            created.append(self)

        def start(self):
            return self

        def alive(self):
            return not self.closed

        def close(self):
            self.closed = True

    monkeypatch.setattr(content_api, "_WORKER", None)
    monkeypatch.setattr(content_api.recognize_ppocrv6, "OcrWorker", FakeWorker)

    first = content_api._worker_for("ppocrv6", ["python", "recognize_ppocrv6.py"], {"column_rescue": False})
    second = content_api._worker_for("ppocrv6", ["python", "recognize_ppocrv6.py"], {"column_rescue": True})

    assert first is not second
    assert first.closed is True
    assert second.config["column_rescue"] is True
    assert len(created) == 2
def test_resolve_punct_backend_prefers_request():
    assert content_api._resolve_punct_backend({"punct_backend": "local"}, {"punct_backend": "off"}) == "local"
    assert content_api._resolve_punct_backend({"punct_backend": "off"}, {"punct_backend": "local"}) == "off"
    assert content_api._resolve_punct_backend({"punct_backend": "bad"}, {"punct_backend": "off"}) == "local"
    assert content_api._resolve_punct_backend({}, {"punct_backend": "off"}) == "off"


def test_region_recog_uses_requested_engine(monkeypatch, tmp_path):
    calls = []

    def fake_run_engine(ctx, image_dir, recog_path, eng):
        calls.append(eng)
        Path(recog_path).write_text('{"region": {"lines": []}}', encoding="utf-8")

    monkeypatch.setattr(content_api, "_run_engine", fake_run_engine)
    ctx = Ctx(str(tmp_path / "progress.json"))
    out = tmp_path / "_recog.json"

    actual = content_api._ensure_region_recog(ctx, tmp_path, out, engine="ppocrv6")

    assert actual == "ppocrv6"
    assert calls == ["ppocrv6"]


def test_region_recog_falls_back_to_lightweight(monkeypatch, tmp_path):
    calls = []

    def fake_run_engine(ctx, image_dir, recog_path, eng):
        calls.append(eng)
        if eng == "ppocrv6":
            raise RuntimeError("paddle missing")
        Path(recog_path).write_text('{"region": {"lines": []}}', encoding="utf-8")

    monkeypatch.setattr(content_api, "_run_engine", fake_run_engine)
    ctx = Ctx(str(tmp_path / "progress.json"))
    out = tmp_path / "_recog.json"

    actual = content_api._ensure_region_recog(ctx, tmp_path, out, engine="ppocrv6")

    assert actual == "ppocrv6_onnx"
    assert calls == ["ppocrv6", "ppocrv6_onnx"]
    assert ctx.read_progress()["fallback"]["from"] == "ppocrv6"



def test_official_low_quality_uses_lightweight_only_when_better(monkeypatch, tmp_path):
    """质量兜底只剩官方 Paddle 档一条：满血/轻量同为 ONNX，降级不可能更好。"""
    calls = []

    def fake_run_engine(ctx, image_dir, recog_path, eng):
        calls.append(eng)
        if eng == "ppocrv6":
            data = {"p001": {"width": 800, "height": 1000, "lines": []}}
        else:
            data = {"p001": {"width": 800, "height": 1000, "lines": [
                {"text": "\u7acb\u5951\u7d04\u4eba" * 30, "box": [600, 100, 680, 900], "score": 0.91, "filter_status": "main_text"}
            ]}}
        Path(recog_path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(content_api, "_run_engine", fake_run_engine)
    out = tmp_path / "_recog.json"
    ctx = Ctx(str(tmp_path / "progress.json"))

    actual = content_api._ensure_recog(ctx, tmp_path, out, engine="ppocrv6")

    assert actual == "ppocrv6_onnx"
    assert calls == ["ppocrv6", "ppocrv6_onnx"]


def test_recog_config_hash_mismatch_forces_rerun(monkeypatch, tmp_path):
    calls = []
    out = tmp_path / "_recog.json"
    out.write_text(json.dumps({
        "_meta": {"engine_config_hash": "old"},
        "p001": {"width": 100, "height": 100, "lines": []},
    }), encoding="utf-8")

    def fake_run_engine(ctx, image_dir, recog_path, eng):
        calls.append(eng)
        Path(recog_path).write_text(json.dumps({
            "p001": {"width": 100, "height": 100, "lines": [{"text": "\u7acb\u5951\u7d04\u4eba\u9858\u5c07\u571f\u5730\u623f\u5c4b\u51fa\u552e\u7d66\u8cb7\u65b9" * 8, "box": [600, 100, 680, 900], "score": 0.93, "filter_status": "main_text"}]},
        }), encoding="utf-8")

    monkeypatch.setattr(content_api, "_run_engine", fake_run_engine)
    ctx = Ctx(str(tmp_path / "progress.json"))

    actual = content_api._ensure_recog(ctx, tmp_path, out, engine="ppocrv6_onnx_high")

    assert actual == "ppocrv6_onnx_high"
    assert calls == ["ppocrv6_onnx_high"]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["_meta"]["engine"] == "ppocrv6_onnx_high"
    assert data["_meta"]["engine_config_hash"] != "old"
    assert data["p001"]["lines"][0]["text"].startswith("\u7acb\u5951")



def test_onnx_high_falls_back_to_lightweight_only(monkeypatch, tmp_path):
    """满血 ONNX 的回退链只有两跳：不许把 Paddle 档拉进来（打包版里没有那个解释器）。"""
    calls = []

    def fake_run_engine(ctx, image_dir, recog_path, eng):
        calls.append(eng)
        if eng == "ppocrv6_onnx_high":
            raise RuntimeError("onnx high failed")
        Path(recog_path).write_text('{"p001": {"width": 100, "height": 100, "lines": []}}', encoding="utf-8")

    monkeypatch.setattr(content_api, "_run_engine", fake_run_engine)
    out = tmp_path / "_recog.json"
    ctx = Ctx(str(tmp_path / "progress.json"))

    actual = content_api._ensure_recog(ctx, tmp_path, out, engine="ppocrv6_onnx_high")

    assert actual == "ppocrv6_onnx"
    assert calls == ["ppocrv6_onnx_high", "ppocrv6_onnx"]


def test_onnx_high_skips_quality_fallback_round_trip(monkeypatch, tmp_path):
    """满血 ONNX 不做「质量差就改投轻量」的兜底——同一批模型、更少后处理，不可能更好。"""
    out = tmp_path / "_recog.json"
    out.write_text('{"p001": {"width": 800, "height": 1000, "lines": []}}', encoding="utf-8")
    ctx = Ctx(str(tmp_path / "progress.json"))

    def boom(*a, **k):
        raise AssertionError("满血 ONNX 不该触发质量兜底")

    monkeypatch.setattr(content_api, "_run_engine", boom)
    assert content_api._maybe_low_recall_lightweight_fallback(
        ctx, tmp_path, out, "ppocrv6_onnx_high") == "ppocrv6_onnx_high"


def test_legacy_cache_without_hash_is_never_reused(tmp_path):
    """无引擎指纹的老缓存一律作废，宁可重识一次。

    以前放行「非默认档 + 无指纹」。DEFAULT_ENGINE 从 ppocrv6_high 换成 ppocrv6_onnx_high 后
    语义翻转：用户升级后选轻量档打开旧批次，会复用由**已被删除的 Paddle 满血档**产出的结果。
    """
    out = tmp_path / "_recog.json"
    out.write_text(json.dumps({
        "p001": {"width": 100, "height": 100, "lines": [],
                 "ocr_meta": {"backend": "ppocrv6", "runtime": "paddle_static"}},
    }), encoding="utf-8")

    assert content_api._recog_cache_valid(out, "ppocrv6_onnx") is False
    assert content_api._recog_cache_valid(out, "ppocrv6_onnx_high") is False


def test_cache_with_matching_hash_is_reused(tmp_path):
    out = tmp_path / "_recog.json"
    out.write_text(json.dumps({"p001": {"width": 100, "height": 100, "lines": []}}), encoding="utf-8")
    content_api._stamp_recog_meta(out, "ppocrv6_onnx")

    assert content_api._recog_cache_valid(out, "ppocrv6_onnx") is True
    assert content_api._recog_cache_valid(out, "ppocrv6_onnx_high") is False   # 换档必须重识
