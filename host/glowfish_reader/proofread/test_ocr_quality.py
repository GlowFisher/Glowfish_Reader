# -*- coding: utf-8 -*-
import ocr_quality


def _page(lines, width=1000, height=1400):
    return {"p001": {"width": width, "height": height, "lines": lines}}


def test_summarize_flags_low_score_repetitive_vertical_garbage():
    text = "\u623f\u52a1\u5802\u5e02" * 12
    data = _page([{
        "text": text,
        "box": [610, 120, 680, 920],
        "score": 0.51,
        "filter_status": "main_text",
    }])

    quality = ocr_quality.summarize_recog(data)

    assert quality["chars"] == len(text)
    assert quality["main_chars"] == len(text)
    assert quality["suspect_garbage_chars"] == len(text)
    assert quality["usable_chars"] == 0


def test_summarize_keeps_normal_vertical_contract_text_usable():
    text = "\u7acb\u5951\u7d04\u4eba\u9858\u5c07\u571f\u5730\u623f\u5c4b\u51fa\u552e\u7d66\u8cb7\u65b9"
    data = _page([{
        "text": text,
        "box": [610, 120, 680, 920],
        "score": 0.93,
        "filter_status": "main_text",
    }])

    quality = ocr_quality.summarize_recog(data)

    assert quality["suspect_garbage_chars"] == 0
    assert quality["usable_chars"] == len(text)


def test_is_better_prefers_less_garbage_with_more_usable_text():
    bad = _page([{
        "text": "\u623f\u52a1\u5802\u5e02" * 12,
        "box": [610, 120, 680, 920],
        "score": 0.51,
        "filter_status": "main_text",
    }, {
        "text": "\u5951\u7d04\u6458\u8981",
        "box": [500, 120, 560, 260],
        "score": 0.88,
        "filter_status": "main_text",
    }])
    good = _page([{
        "text": "\u7acb\u5951\u7d04\u4eba\u9858\u5c07\u571f\u5730\u623f\u5c4b\u51fa\u552e\u7d66\u8cb7\u65b9" * 6,
        "box": [610, 120, 680, 920],
        "score": 0.93,
        "filter_status": "main_text",
    }])

    assert ocr_quality.is_better(good, bad)



def test_summarize_ignores_internal_recog_meta_page():
    text = "\u7acb\u5951\u7d04\u4eba" * 31
    data = {
        "_meta": {"engine": "ppocrv6_high", "engine_config_hash": "abc"},
        "p001": {"width": 800, "height": 1000, "lines": [
            {"text": text, "box": [600, 100, 680, 900], "score": 0.93, "filter_status": "main_text"}
        ]},
    }

    quality = ocr_quality.summarize_recog(data)

    assert quality["low_pages"] == 0
    assert quality["usable_chars"] == len(text)
