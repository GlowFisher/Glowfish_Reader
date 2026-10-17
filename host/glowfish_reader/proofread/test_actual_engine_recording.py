# -*- coding: utf-8 -*-
import json
from pathlib import Path

import content_api


class FakeCtx:
    def __init__(self, root):
        self.work = root
        self.progress_path = root / "progress.json"

    def read_progress(self):
        if not self.progress_path.exists():
            return {}
        return json.loads(self.progress_path.read_text(encoding="utf-8"))

    def write_progress(self, data):
        self.progress_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_load_proof_records_actual_fallback_engine(monkeypatch, tmp_path):
    calls = []

    def fake_run_engine(ctx, image_dir, recog_path, eng):
        calls.append(eng)
        if eng == "ppocrv6":
            raise RuntimeError("paddle missing")
        recog_path.write_text(json.dumps({
            "p001": {"image": "p001.jpg", "width": 1, "height": 1, "lines": []}
        }), encoding="utf-8")

    monkeypatch.setattr(content_api, "_run_engine", fake_run_engine)

    ctx = FakeCtx(tmp_path)
    image_dir = tmp_path / "imgs"
    image_dir.mkdir()
    proof = content_api._load_proof(ctx, "batch1", image_dir, "src", engine="ppocrv6")

    assert calls == ["ppocrv6", "ppocrv6_onnx"]
    assert proof["engine"] == "ppocrv6_onnx"
    assert json.loads((tmp_path / "batch1" / "proof.json").read_text(encoding="utf-8"))["engine"] == "ppocrv6_onnx"


def test_load_proof_records_success_engine(monkeypatch, tmp_path):
    def fake_run_engine(ctx, image_dir, recog_path, eng):
        recog_path.write_text(json.dumps({
            "p001": {"image": "p001.jpg", "width": 1, "height": 1, "lines": []}
        }), encoding="utf-8")

    monkeypatch.setattr(content_api, "_run_engine", fake_run_engine)

    ctx = FakeCtx(tmp_path)
    image_dir = tmp_path / "imgs"
    image_dir.mkdir()
    proof = content_api._load_proof(ctx, "batch1", image_dir, "src", engine="ppocrv6")

    assert proof["engine"] == "ppocrv6"
