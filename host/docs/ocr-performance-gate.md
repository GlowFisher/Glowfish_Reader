# OCR runtime performance gate

The public OCR component remains opt-in until both source and frozen A-B gates pass.
The gate compares the preserved legacy resident worker with
`glowfish_ocr.ResidentOcrService` in separate processes.

## Source benchmark

Run from the Host repository root with the project interpreter:

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD\components\ocr\src"
python .\scripts\run_ocr_runtime_ab.py `
  --entry .\glowfish_reader\proofread\desktop_app.py `
  --fixture .\components\ocr\bench\fixtures\vertical_cht_clean.png `
  --output-dir .\.tmp\ocr-ab-source
```

## Frozen benchmark

After building the PyInstaller onedir, pass the packaged desktop executable:

```powershell
python .\scripts\run_ocr_runtime_ab.py `
  --executable "D:\short-build\dist\glowfish_reader\Glowfish Reader V1.0.1.exe" `
  --fixture .\components\ocr\bench\fixtures\vertical_cht_clean.png `
  --output-dir .\.tmp\ocr-ab-frozen
```

Each mode writes a structured report plus `summary.json`. Acceptance requires:

- equivalent normalized OCR output and at least one recognized line;
- reuse of the prewarmed resident worker for all measured iterations;
- release of the worker after the configured idle interval;
- component median warm latency within 15% of legacy;
- component prewarm latency within 25% of legacy;
- component process-tree RSS growth no more than 256 MB above legacy.

Thresholds are CLI options so release engineering can tighten them after repeated
measurements. A failed threshold returns a nonzero exit code and records every failure
in `summary.json`.

## Reproducible build inputs

`release.ps1` accepts `-Python` or `GLOWFISH_BUILD_PYTHON`, and `-BuildRoot` or
`GLOWFISH_BUILD_ROOT`. Use short paths on Windows to avoid PyInstaller path-length
failures. The release script still runs component validation, deterministic UI build,
asset verification, dependency preflight, frozen self-tests, and payload auditing.
