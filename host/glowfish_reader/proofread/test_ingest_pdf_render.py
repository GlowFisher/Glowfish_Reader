from pathlib import Path

import fitz
from PIL import Image

import ingest


def _make_pdf(path: Path, page_builder, *, rotation=0):
    doc = fitz.open()
    page = doc.new_page(width=200, height=300)
    page_builder(page)
    if rotation:
        page.set_rotation(rotation)
    doc.save(path)
    doc.close()


def _pixel(image, x_ratio, y_ratio):
    return image.getpixel((int(image.width * x_ratio), int(image.height * y_ratio)))


def test_explode_renders_both_image_halves_and_vector_content(tmp_path):
    pdf = tmp_path / "two-halves.pdf"

    def build(page):
        page.draw_rect(fitz.Rect(0, 0, 200, 145), color=(1, 0, 0), fill=(1, 0, 0))
        page.draw_rect(fitz.Rect(0, 155, 200, 300), color=(0, 0, 1), fill=(0, 0, 1))
        page.draw_rect(fitz.Rect(80, 130, 120, 170), color=(0, 0, 0), fill=(0, 0, 0))

    _make_pdf(pdf, build)
    produced = ingest.explode([pdf], tmp_path / "out", dpi=72)

    assert [p.name for p in produced] == ["0001_two-halves_p1.png"]
    with Image.open(produced[0]) as image:
        assert image.mode == "RGB"
        assert image.size == (200, 300)
        assert _pixel(image, 0.1, 0.1)[0] > 240
        assert _pixel(image, 0.1, 0.9)[2] > 240
        assert max(_pixel(image, 0.5, 0.5)) < 20


def test_explode_preserves_six_horizontal_bands(tmp_path):
    pdf = tmp_path / "six-bands.pdf"
    colors = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1)]

    def build(page):
        for index, color in enumerate(colors):
            page.draw_rect(
                fitz.Rect(0, index * 50, 200, (index + 1) * 50),
                color=color,
                fill=color,
            )

    _make_pdf(pdf, build)
    output = ingest.explode([pdf], tmp_path / "out", dpi=72)[0]

    with Image.open(output) as image:
        samples = [_pixel(image, 0.5, (index + 0.5) / 6) for index in range(6)]
    for actual, expected in zip(samples, colors):
        expected_rgb = tuple(round(channel * 255) for channel in expected)
        assert all(abs(a - e) <= 2 for a, e in zip(actual, expected_rgb))


def test_vector_single_scan_and_rotated_pages_keep_page_geometry(tmp_path):
    vector_pdf = tmp_path / "vector.pdf"
    _make_pdf(vector_pdf, lambda page: page.insert_text((30, 80), "VECTOR", fontsize=24))
    vector_output = ingest.explode([vector_pdf], tmp_path / "vector-out", dpi=72)[0]
    with Image.open(vector_output) as image:
        assert image.mode == "RGB"
        assert image.getbbox() == (0, 0, 200, 300)
        assert image.convert("L").getextrema()[0] < 100

    scan_pdf = tmp_path / "scan.pdf"
    _make_pdf(
        scan_pdf,
        lambda page: page.draw_rect(
            fitz.Rect(0, 0, 200, 300), color=(0.2, 0.4, 0.6), fill=(0.2, 0.4, 0.6)
        ),
    )
    scan_output = ingest.explode([scan_pdf], tmp_path / "scan-out", dpi=72)[0]
    with Image.open(scan_output) as image:
        assert image.size == (200, 300)
        assert _pixel(image, 0.5, 0.5) == (51, 102, 153)

    rotated_pdf = tmp_path / "rotated.pdf"
    _make_pdf(
        rotated_pdf,
        lambda page: page.draw_rect(
            fitz.Rect(0, 0, 200, 300), color=(0, 0, 0), fill=(1, 1, 1)
        ),
        rotation=90,
    )
    rotated_output = ingest.explode([rotated_pdf], tmp_path / "rotated-out", dpi=72)[0]
    with Image.open(rotated_output) as image:
        assert image.size == (300, 200)


def test_explode_ordered_uses_same_complete_page_renderer(tmp_path):
    pdf = tmp_path / "ordered.pdf"

    def build(page):
        page.draw_rect(fitz.Rect(0, 0, 200, 150), color=(1, 0, 0), fill=(1, 0, 0))
        page.draw_rect(fitz.Rect(0, 150, 200, 300), color=(0, 0, 1), fill=(0, 0, 1))

    _make_pdf(pdf, build)
    output = ingest.explode_ordered(
        [{"path": str(pdf), "type": "pdfpage", "page": 1}],
        tmp_path / "ordered-out",
        dpi=72,
    )[0]
    assert output.name == "0001_ordered_p1.png"
    with Image.open(output) as image:
        assert image.mode == "RGB"
        assert _pixel(image, 0.5, 0.1)[0] > 240
        assert _pixel(image, 0.5, 0.9)[2] > 240


def test_pdf_render_error_includes_source_and_one_based_page(tmp_path):
    class BrokenPage:
        def get_pixmap(self, **_kwargs):
            raise ValueError("damaged stream")

    class BrokenDoc:
        name = "ignored.pdf"

        def __getitem__(self, _index):
            return BrokenPage()

    try:
        ingest._save_pdf_page(BrokenDoc(), 2, tmp_path / "unused.png", 72, "broken.pdf")
    except RuntimeError as error:
        assert str(error) == "broken.pdf page 3: damaged stream"
    else:
        raise AssertionError("render failure was not reported")
