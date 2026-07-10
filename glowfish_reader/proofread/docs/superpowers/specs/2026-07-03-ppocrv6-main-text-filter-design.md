# PP-OCRv6 Main Text Filter Design

## Goal

Reduce non-body OCR output from the default PP-OCRv6 engine, especially seals, centerfold/catalog marks, and English watermarks, while keeping normal horizontal and vertical body text.

## Approach

Add a conservative post-OCR filter for PP-OCRv6 lines. The filter receives the existing line contract (`text`, `box`, `score`) plus page width and height, and returns only lines that look like user-editable source text. It does not change the `_recog.json` schema.

The first version uses deterministic text and geometry rules instead of adding another model dependency to PP-OCRv6. This keeps startup and packaging behavior stable. The previous VL layout approach remains useful as a later stronger gate, but PP-OCRv6 can get immediate protection with a smaller and testable layer.

## Rules

- Drop obvious English or software watermarks when they are mostly ASCII and look like URLs, emails, "scan", "watermark", "sample", "copyright", or similar machine-added text.
- Drop seal-like short labels when the text contains seal/stamp vocabulary and the box is small or in page margins.
- Drop page-center/catalog fragments when they sit near the vertical centerline, are narrow, and look like short catalog/page markers rather than body text.
- Keep ordinary Chinese body text, and keep body text that contains a little English when it does not match watermark patterns.

## Integration

`recognize_ppocrv6.recognize_one()` builds raw line dictionaries as it already does, then calls `ocr_filter.filter_page_lines(lines, width, height)` before returning the page result.

## Tests

Add unit tests for the filter itself and one integration-style test using the fake PP-OCRv6 engine to prove `recognize_one()` returns filtered lines.
