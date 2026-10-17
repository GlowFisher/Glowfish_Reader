# PP-OCRv6 Main Text Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a conservative post-OCR filter to PP-OCRv6 so non-body seal, page-center/catalog, and English watermark text is excluded from editable OCR results.

**Architecture:** Create a focused `ocr_filter.py` module with pure functions over the existing line contract. Wire it into `recognize_ppocrv6.recognize_one()` after raw PaddleOCR output is converted to project lines.

**Tech Stack:** Python 3, pytest, existing PP-OCRv6 line contract.

---

### Task 1: Filter Module

**Files:**
- Create: `glowfish_reader/proofread/ocr_filter.py`
- Test: `glowfish_reader/proofread/test_ocr_filter.py`

- [ ] **Step 1: Write failing tests**

Add tests that call `filter_page_lines(lines, width, height)` and assert that body text remains while English watermark, seal-like short labels, and centerline catalog fragments are removed.

- [ ] **Step 2: Verify tests fail**

Run: `python -m pytest test_ocr_filter.py -q` from `glowfish_reader/proofread`.
Expected: import failure for `ocr_filter`.

- [ ] **Step 3: Implement minimal filter**

Create helpers for box geometry, mostly-ASCII detection, watermark patterns, seal terms, and page-center marker detection.

- [ ] **Step 4: Verify tests pass**

Run: `python -m pytest test_ocr_filter.py -q` from `glowfish_reader/proofread`.
Expected: all tests pass.

### Task 2: PP-OCRv6 Integration

**Files:**
- Modify: `glowfish_reader/proofread/recognize_ppocrv6.py`
- Modify: `glowfish_reader/proofread/test_ppocrv6_engine.py`

- [ ] **Step 1: Write failing integration test**

Extend the fake PP-OCRv6 output with a body line and a watermark line, then assert `recognize_one()` returns only the body line.

- [ ] **Step 2: Verify test fails**

Run: `python -m pytest test_ppocrv6_engine.py::test_recognize_one_filters_non_body_noise -q` from `glowfish_reader/proofread`.
Expected: assertion failure because the watermark is still present.

- [ ] **Step 3: Wire filter into `recognize_one()`**

Import `ocr_filter` and call `filter_page_lines(lines, width, height)` before returning the page dict.

- [ ] **Step 4: Verify targeted tests pass**

Run: `python -m pytest test_ocr_filter.py test_ppocrv6_engine.py -q` from `glowfish_reader/proofread`.
Expected: all targeted tests pass.
