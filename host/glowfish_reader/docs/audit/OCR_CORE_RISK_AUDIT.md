# OCR Core Risk Audit

Update date: 2026-07-07

This note records the read-only high-risk OCR/core-flow inspection from the
code slimming audit. It is not a refactor plan and does not authorize direct
deletion inside the OCR pipeline.

## Product Boundary

GlowFish Reader is a local historical-document OCR and proofreading reader. The
core product promise is:

- local import of images/PDFs
- local OCR for ancient books, newspapers, and handwritten archives
- local image/text proofreading
- local search, annotations, and export
- no source images uploaded to cloud OCR services

Remote calls may exist for licensing, notices, and updates, but those are
separate from the OCR recognition path.

## Core Import And OCR Flow

Primary import flow:

1. `proofread/content_api.py:/api/upload`
2. `proofread/content_api.py:/api/open`
3. `ingest.explode_ordered(...)`
4. `content_api._load_proof(...)`
5. `content_api._ensure_recog(...)`
6. `content_api._run_engine(...)`
7. `proofread/recognize_ppocrv6.py` or `proofread/recognize_ppocrv6_onnx.py`
8. `proof_model.load_or_build(...)`
9. `proof.json` saved under the local user work directory

Manual region re-OCR flow:

1. `proofread/content_api.py:/api/reocr_region`
2. crop selected region into a local temporary `_region_ocr/_src/region.png`
3. `content_api._ensure_region_recog(...)`
4. map crop boxes back through `ocr_rescue.map_crop_line(...)`
5. return local OCR lines to the frontend

## Engine Registry

`proofread/engines.py` is the current engine source of truth:

| Engine | Role | Risk |
|---|---|---|
| `ppocrv6` | Default quality-first local PaddleOCR PP-OCRv6 path | High |
| `ppocrv6_onnx` | Lightweight local ONNX Runtime fallback path | High |
| `onnx` | Compatibility alias for `ppocrv6_onnx` | Keep |
| `paddle` | Historical comparison path | Do not remove without separate migration |

The legacy `onnx` name is intentionally preserved because saved settings may
still contain it.

## High-Risk Files

Do not prune or merge these during routine cleanup:

- `proofread/content_api.py`
- `proofread/engines.py`
- `proofread/recognize_ppocrv6.py`
- `proofread/recognize_ppocrv6_onnx.py`
- `proofread/recognize.py`
- `proofread/ocr_rescue.py`
- `proofread/ocr_filter.py`
- `proofread/ocr_quality.py`
- `proofread/proof_model.py`
- `bench/run_bench.py`
- `bench/eval_cer.py`

Reason: these files define OCR dispatch, fallback, vertical-column rescue,
noise retention, page reading order, and regression measurement.

## Recognizer Duplication

`recognize_ppocrv6.py` and `recognize_ppocrv6_onnx.py` intentionally share a
large amount of structure:

- PaddleX environment setup
- image listing
- EXIF normalization
- enhanced OCR image generation
- bounding-box conversion
- full-page OCR
- column rescue
- dedupe/filter pass
- resident worker protocol
- CLI entry point

This is real duplication, but it spans two different runtimes:

- full PaddleOCR through a Paddle-capable interpreter
- ONNX Runtime through the local app interpreter

Classification: high risk. Do not merge without a dedicated refactor, golden
sample outputs, and full bench coverage.

## Offline Boundary Findings

Read-only scan found no explicit source-image upload to an external OCR service
inside the OCR path.

Network-related code observed:

- licensing client/server calls
- notice manifest fetch
- update manifest/download
- local desktop self-check against `127.0.0.1`
- PaddleX/HuggingFace endpoint defaults in OCR setup

Important risk:

`recognize_ppocrv6.py` and `recognize_ppocrv6_onnx.py` set PaddleX/HuggingFace
model source defaults and a local cache path. This does not upload images, but
if required model files are missing, PaddleOCR/PaddleX may attempt to download
model assets.

For a strict offline release, verify model completeness before shipping and run
an offline/no-network smoke test.

## Fallback Behavior

Primary OCR fallback points:

- `_ensure_recog(...)` falls back from a non-lightweight engine to
  `ppocrv6_onnx` when startup or recognition fails.
- `_maybe_low_recall_lightweight_fallback(...)` can replace a bad `ppocrv6`
  result with `ppocrv6_onnx` if OCR quality metrics show low recall or garbage
  vertical columns and the lightweight result is better.
- `_ensure_region_recog(...)` applies similar fallback for manual region OCR.

The fallback progress marker is intentionally preserved by `_finish_progress`.

Classification: high-risk behavior. Do not simplify without preserving progress
JSON semantics and UI fallback banner behavior.

## Proof Contract

`proof_model.build_proof(...)` keeps OCR noise lines in `proof.json` while
excluding them from the default editable/export order.

Relevant contract:

- main OCR lines become editable proof lines
- noise lines remain recoverable in `noise_lines`
- default order is right-to-left vertical reading order
- export uses the proof order, not raw OCR order

Classification: high risk. Do not delete noise-handling fields or reorder logic
as dead data.

## Existing Focused Verification

The following focused suite passed after forcing pytest temporary files into
the project workspace:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  proofread\test_ppocrv6_engine.py `
  proofread\test_ppocrv6_filter_integration.py `
  proofread\test_content_fallback.py `
  proofread\test_desktop_ocr_dispatch.py `
  proofread\test_ocr_quality.py `
  proofread\test_ocr_filter.py `
  proofread\test_proof_model.py `
  -q -p no:cacheprovider --basetemp .pytest_tmp_core
```

Result:

```text
40 passed, 12 warnings in 2.17s
```

The first run without `--basetemp` failed because pytest tried to access
`C:\Users\15346\AppData\Local\Temp\pytest-of-15346`, which was permission
denied. That was an environment temporary-directory issue, not an OCR behavior
failure.

Warnings:

- `ocr_filter.py` uses `Image.Image.getdata`, deprecated and scheduled for
  removal in Pillow 14 on 2027-10-15.

## Required Verification Before OCR Refactor

Before any OCR/core slimming change, run at least:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  proofread\test_ppocrv6_engine.py `
  proofread\test_ppocrv6_filter_integration.py `
  proofread\test_content_fallback.py `
  proofread\test_desktop_ocr_dispatch.py `
  proofread\test_ocr_quality.py `
  proofread\test_ocr_filter.py `
  proofread\test_proof_model.py `
  -q -p no:cacheprovider --basetemp .pytest_tmp_core

.\.venv\Scripts\python.exe bench\run_bench.py --engine ppocrv6_onnx --only 手写
```

If a PaddleOCR-capable interpreter is available, also run the `ppocrv6` bench
with `SHUPAI_PADDLE_PY` or `--paddle-py`.

## Cleanup Guidance

Safe now:

- documentation only
- test command documentation
- offline deployment checklist documentation

Do not touch now:

- OCR worker protocol
- engine aliases
- `ppocrv6` / `ppocrv6_onnx` shared structure
- fallback reason strings
- proof `noise_lines`
- default vertical reading order
- bench `recog_to_pred_rtl`

Potential future work:

1. Add an offline model completeness check.
2. Add a no-network OCR smoke test for packaged/offline release.
3. Replace deprecated Pillow `getdata` usage before Pillow 14.
4. Only then consider extracting a shared recognizer support module.
