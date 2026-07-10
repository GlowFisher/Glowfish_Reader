# -*- coding: utf-8 -*-
import ocr_filter as f


def test_filter_page_lines_drops_noise_but_keeps_body_text():
    lines = [
        {"text": "臣等谨奏为查明地方情形", "box": [720, 90, 760, 880], "score": 0.96},
        {"text": "Scanned by CamScanner", "box": [80, 20, 620, 55], "score": 0.99},
        {"text": "藏书印", "box": [28, 880, 98, 948], "score": 0.91},
        {"text": "目录三", "box": [385, 120, 415, 220], "score": 0.88},
        {"text": "条约第 Article 4 款照办", "box": [610, 100, 660, 720], "score": 0.94},
    ]

    kept = f.filter_page_lines(lines, width=800, height=1000)

    assert [line["text"] for line in kept] == [
        "臣等谨奏为查明地方情形",
        "条约第 Article 4 款照办",
    ]


def test_filter_page_lines_keeps_short_body_when_not_noise_shaped():
    lines = [
        {"text": "奏报", "box": [700, 100, 745, 420], "score": 0.9},
        {"text": "三月", "box": [645, 100, 690, 390], "score": 0.9},
    ]

    kept = f.filter_page_lines(lines, width=800, height=1000)

    assert [line["text"] for line in kept] == ["奏报", "三月"]


def test_filter_page_lines_drops_sample_stamp_and_side_catalog_noise():
    lines = [
        {"text": "满迎家", "box": [2492, 466, 2629, 913], "score": 0.7065},
        {"text": "高氏宗譜", "box": [276, 654, 341, 938], "score": 0.5656},
        {"text": "EALL", "box": [290, 1047, 339, 1214], "score": 0.7699},
        {"text": "甲子一週而安居暇食不親藥餌不習導引不可謂不", "box": [1061, 685, 1173, 2068], "score": 0.9365},
        {"text": "鶴翁之家把酒言歡恨相見之晚歸而語", "box": [2358, 700, 2446, 2059], "score": 0.9891},
    ]

    kept = f.filter_page_lines(lines, width=3003, height=2637)

    assert [line["text"] for line in kept] == [
        "甲子一週而安居暇食不親藥餌不習導引不可謂不",
        "鶴翁之家把酒言歡恨相見之晚歸而語",
    ]


def test_filter_page_lines_drops_red_stamp_region(tmp_path):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (800, 1000), (245, 245, 245))
    draw = ImageDraw.Draw(img)
    draw.rectangle([60, 620, 180, 900], fill=(225, 130, 130))
    path = tmp_path / "page.jpg"
    img.save(path)
    lines = [
        {"text": "制务务证", "box": [70, 650, 170, 880], "score": 0.62},
        {"text": "正文正文正文正文正文", "box": [610, 120, 680, 880], "score": 0.97},
    ]

    kept = f.filter_page_lines(lines, width=800, height=1000, image_path=path)

    assert [line["text"] for line in kept] == ["正文正文正文正文正文"]

def test_image_ratios_uses_pillow_14_flattened_pixel_api():
    class Crop:
        width = 2
        height = 1

        def convert(self, mode):
            assert mode == "RGB"
            return self

        def get_flattened_data(self):
            return [(220, 80, 80), (30, 30, 30)]

        def getdata(self):
            raise AssertionError("deprecated getdata should not be used")

    class Image:
        width = 2
        height = 1

        def crop(self, box):
            assert box == (0, 0, 2, 1)
            return Crop()

    ratios = f._image_ratios(Image(), {"box": [0, 0, 2, 1]})

    assert ratios["red"] == 0.5
    assert ratios["pale_red"] == 0.5
