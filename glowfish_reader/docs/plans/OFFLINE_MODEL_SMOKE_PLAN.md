# Offline Model And No-Network Smoke Plan

Update date: 2026-07-07

This is a plan only. No network isolation test has been executed in this step,
and no OCR/model code has been changed.

## Goal

Verify that GlowFish can run its local OCR/proofing path without uploading
source images or fetching missing model assets during recognition.

This plan separates three concerns:

- packaged/lightweight local OCR through `ppocrv6_onnx`
- full quality-first OCR through `ppocrv6`
- local punctuation through `proofread/models/punct`

## Current Model Inventory

Observed local model files:

| Area | Required files observed |
|---|---|
| `proofread/models/ppocrv6_onnx/det` | `inference.json`, `inference.onnx`, `inference.yml` |
| `proofread/models/ppocrv6_onnx/rec` | `inference.json`, `inference.onnx`, `inference.yml` |
| `proofread/models/punct` | `meta.json`, `model.onnx`, `vocab.txt` |

The PyInstaller spec includes `models/ppocrv6_onnx`. For punctuation, the spec
prefers `model_int8.onnx` when present, plus `vocab.txt` and `meta.json`. The
source tree currently has `model.onnx`, not `model_int8.onnx`, so packaging
needs an explicit check if punctuation must be bundled.

## Known Network-Touching Areas

Not part of OCR image upload:

- licensing calls
- notice manifest fetch
- update manifest/download
- localhost desktop self-check

OCR/model-related risk:

- `recognize_ppocrv6.py` and `recognize_ppocrv6_onnx.py` set PaddleX model
  source defaults and HuggingFace mirror endpoint values.
- This does not upload images, but PaddleOCR/PaddleX may try to download model
  assets if local model/cache files are incomplete.

## Static Completeness Checks

Run before any network-isolated smoke test:

```powershell
Test-Path proofread\models\ppocrv6_onnx\det\inference.onnx
Test-Path proofread\models\ppocrv6_onnx\det\inference.json
Test-Path proofread\models\ppocrv6_onnx\det\inference.yml
Test-Path proofread\models\ppocrv6_onnx\rec\inference.onnx
Test-Path proofread\models\ppocrv6_onnx\rec\inference.json
Test-Path proofread\models\ppocrv6_onnx\rec\inference.yml
Test-Path proofread\models\punct\vocab.txt
Test-Path proofread\models\punct\meta.json
Test-Path proofread\models\punct\model_int8.onnx
Test-Path proofread\models\punct\model.onnx
```

Pass criteria:

- all `ppocrv6_onnx` files are present
- at least one punctuation model is present: `model_int8.onnx` or `model.onnx`
- if building a release package, the spec includes the actual punctuation model
  file that will be shipped

## Environment Isolation For Smoke Test

Use an isolated data/cache root so the test does not silently pass because of
old user cache data:

```powershell
$env:SHUPAI_DATA_DIR = "$PWD\.offline_smoke_data"
$env:PADDLE_PDX_CACHE_HOME = "$PWD\.offline_smoke_paddlex_cache"
$env:HTTP_PROXY = "http://127.0.0.1:9"
$env:HTTPS_PROXY = "http://127.0.0.1:9"
$env:ALL_PROXY = "http://127.0.0.1:9"
$env:NO_PROXY = "127.0.0.1,localhost"
```

For a stronger test, use Windows Firewall or another local network-blocking
method to deny outbound network access for the tested Python or packaged EXE.
Do not rely only on proxy variables if the goal is a release-grade offline
claim.

## Lightweight OCR Smoke

Run the local ONNX path first:

```powershell
.\.venv\Scripts\python.exe bench\run_bench.py --engine ppocrv6_onnx --only 手写
```

Pass criteria:

- command completes without model download attempts
- `_recog.json` is produced
- bench reports a valid F1/CER summary
- no external network connection is observed

This is the minimum smoke for a local/offline fallback OCR path.

## Full PP-OCRv6 Smoke

Only run when a PaddleOCR-capable interpreter is available:

```powershell
$env:SHUPAI_PADDLE_PY = "C:\path\to\paddle-env\python.exe"
.\.venv\Scripts\python.exe bench\run_bench.py --engine ppocrv6 --only 手写
```

Pass criteria:

- full engine starts without downloading assets
- bench completes and writes a report
- output remains local
- if local cache is empty, all required PaddleOCR/PaddleX model assets must
  already be bundled or pre-seeded

If this path attempts network access, treat it as a packaging/deployment
incompleteness issue rather than proof of image upload.

## Local Punctuation Smoke

Check availability:

```powershell
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'proofread'); import punctuate_local; print(punctuate_local.available())"
```

Run a minimal punctuation call only after availability is true:

```powershell
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'proofread'); import punctuate_local; print(punctuate_local.local_punctuate(['子曰学而时习之']))"
```

Pass criteria:

- local ONNX Runtime session opens
- no torch/model download is attempted
- output preserves the original CJK character sequence

## Packaged App Smoke

For a release build:

1. Build the package.
2. Inspect the output directory for:
   - `models/ppocrv6_onnx/det/*`
   - `models/ppocrv6_onnx/rec/*`
   - `models/punct/meta.json`
   - `models/punct/vocab.txt`
   - the actual punctuation ONNX file intended for release
3. Run the packaged app with outbound network blocked.
4. Import a tiny local image/PDF sample.
5. Confirm OCR, proofing, save, export, and app shutdown all work locally.

Pass criteria:

- no source image leaves the machine
- no model download is required
- fallback banner behavior remains understandable if an engine is unavailable
- local export files are produced successfully

## Failure Triage

If the lightweight path tries to download:

- check `proofread/models/ppocrv6_onnx`
- check PaddleOCR/PaddleX version behavior
- verify model dirs are passed explicitly to PaddleOCR

If the full `ppocrv6` path tries to download:

- check `PADDLE_PDX_CACHE_HOME`
- pre-seed PaddleX/PaddleOCR model cache
- document the cache as a release prerequisite

If punctuation is unavailable:

- check whether `model_int8.onnx` or `model.onnx` is expected
- update packaging spec or regenerate the intended model artifact

## Recommended Future Automation

Add a script such as `scripts/offline_model_check.py` that:

- verifies required model files and minimum sizes
- checks package output after build
- starts a local OCR smoke with a temporary data root
- optionally fails if outbound network is observed by an external monitor

Keep the first version read-only and diagnostic; do not make it delete caches or
change model files automatically.
