# -*- coding: utf-8 -*-
import types

from PIL import Image

import recognize_ppocrv6 as r


class FakePPOCRv6WithNoise:
    def predict(self, path):
        return [types.SimpleNamespace(json={"res": {
            "rec_texts": ["正文正文正文", "Scanned by CamScanner"],
            "rec_scores": [0.96, 0.99],
            "rec_polys": [
                [[120, 60], [150, 60], [150, 520], [120, 520]],
                [[40, 10], [700, 10], [700, 45], [40, 45]],
            ],
        }})]


def test_recognize_one_marks_non_body_noise_without_dropping(tmp_path):
    img = tmp_path / "p001.png"
    Image.new("RGB", (800, 1000), (255, 255, 255)).save(img)
    norm = tmp_path / "_img"
    norm.mkdir()

    out = r.recognize_one(FakePPOCRv6WithNoise(), img, norm)

    assert [line["text"] for line in out["lines"]] == ["正文正文正文", "Scanned by CamScanner"]
    assert out["lines"][0]["filter_status"] == "main_text"
    assert out["lines"][1]["filter_status"] == "noise"
    assert out["lines"][1]["filter_reason"] == "watermark"
