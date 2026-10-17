# Final Regression Plan

Update date: 2026-07-07

This is the final regression and reporting plan for the current audit/slimming
track. It is a plan only; no final full regression run is recorded in this file.

## Current Audit Baseline

Known protection and audit commits:

- `c85b81e1 chore: snapshot pre-audit working tree`
- `96896d8d chore: prune low-risk dead code`
- `133f6912 docs: record audit risk tracks`
- `c228bce4 test: lock signing canonicalization contract`

Current branch:

- `audit-snapshot-20260706-232102`

Use this branch and the pre-audit snapshot commit/bundle as rollback anchors.

## Temporary Directory Rule

On this Windows machine, pytest may fail when it tries to use:

```text
C:\Users\15346\AppData\Local\Temp\pytest-of-15346
```

Use project-local `--basetemp` paths for all pytest runs:

```powershell
-p no:cacheprovider --basetemp .pytest_tmp_<suite>
```

Do not interpret default-temp permission errors as product regressions.

## Mandatory Automated Regression

Run these before reporting a cleanup/refactor as complete.

### 1. Core Proofread Tests

```powershell
.\.venv\Scripts\python.exe -m pytest proofread -q -p no:cacheprovider --basetemp .pytest_tmp_proofread
```

Purpose:

- app API behavior
- import/load/save contracts
- OCR dispatch/fallback unit coverage
- proof model and export logic
- frontend static contract tests
- update/notice/settings/auth coverage

### 2. License Server And Client Tests

Run the legacy license server tests separately:

```powershell
.\.venv\Scripts\python.exe -m pytest license_server\tests -q -p no:cacheprovider --basetemp .pytest_tmp_license_server
```

Run client-side licensing tests:

```powershell
.\.venv\Scripts\python.exe -m pytest proofread\licensing\tests -q -p no:cacheprovider --basetemp .pytest_tmp_licensing
```

Purpose:

- trial / activation / check / deactivate
- Ed25519 signed envelope compatibility
- `_canon` byte-level protocol lock
- local license API behavior

### 3. High-Risk OCR Focus Suite

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

Previously observed result on this audit branch:

```text
40 passed, 12 warnings
```

Purpose:

- OCR contract
- rescue/filter/quality behavior
- fallback to `ppocrv6_onnx`
- desktop `--ocr` dispatch
- default right-to-left proof order

### 4. Export And Annotation Focus Suite

```powershell
.\.venv\Scripts\python.exe -m pytest `
  proofread\test_export_inline_annotations.py `
  proofread\test_export_selected_pages.py `
  proofread\test_export_annots.py `
  proofread\test_export_last_dir_setting.py `
  -q -p no:cacheprovider --basetemp .pytest_tmp_export
```

Purpose:

- DOCX/Markdown/TXT export contracts
- selected-page export
- inline annotation behavior
- image/annotation export integration

### 5. Frontend Syntax Checks

Run if Node.js is available:

```powershell
node --check proofread\static\app.js
node --check proofread\static\viewer.js
node --check proofread\static\editor.js
node --check proofread\static\settings.js
node --check proofread\static\annotations.js
node --check proofread\static\importer.js
node --check proofread\static\notebook.js
node --check proofread\static\update.js
```

Purpose:

- catch syntax regressions in script-tag frontend modules
- protect import, reader, annotation, notebook, settings, and update flows

### 6. Desktop Self-Test

```powershell
.\.venv\Scripts\python.exe proofread\desktop_app.py --selftest
```

Purpose:

- local server can start
- `/api/me` and settings endpoints respond
- desktop/headless startup path is intact

## Bench Regression

### Required Lightweight Bench

```powershell
.\.venv\Scripts\python.exe bench\run_bench.py --engine ppocrv6_onnx --only 手写
```

Previously observed audit result:

```text
F1=0.967 recall=0.970 precision=0.964 CER=0.076
```

Pass criteria:

- command completes
- generated report exists under `bench/out/`
- hand-written set stays above gate `F1 >= 0.92`
- no unexpected crash or model download requirement

### Conditional Full PP-OCRv6 Bench

Only run when a PaddleOCR-capable interpreter is available:

```powershell
$env:SHUPAI_PADDLE_PY = "C:\path\to\paddle-env\python.exe"
.\.venv\Scripts\python.exe bench\run_bench.py --engine ppocrv6 --only 手写
```

Pass criteria:

- command completes
- no unexpected fallback-only success is mistaken for full-engine success
- report is captured with engine name and F1/CER

### Printed Material Gap

`bench/gold_printed/` currently needs real printed-material gold data for
release-grade printed-page claims. If no real printed set is available, report
the printed bench as "not verified" instead of implying coverage.

## Offline And Model Smoke

Use `OFFLINE_MODEL_SMOKE_PLAN.md` for the no-network/model-completeness plan.

Minimum final report fields:

- `ppocrv6_onnx` model files present: yes/no
- punctuation model present: `model_int8.onnx`, `model.onnx`, or missing
- packaged spec includes intended punctuation model: yes/no/not checked
- no-network smoke executed: yes/no
- if executed, external network observed: yes/no

## Account/Member Server Track

The phone/member account system lives at `license_server/` (merged from the former
`user_login_1/server/` on 2026-07-08; see `docs/audit/AUTH_SERVER_TRACKS.md`). Run:

```powershell
cd "D:\CC-first\glowfish-reader\glowfish_reader\license_server"
..\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp ..\.pytest_tmp_license_server
```

If imports point to an older checkout, fix `PYTHONPATH`, working directory, or
interpreter setup before interpreting failures as regressions.

## Manual Smoke Checklist

Run after automated tests if preparing a release or a larger cleanup merge:

1. Start the app locally.
2. Import a small local image set.
3. Confirm OCR progress moves through import/OCR/done.
4. Open a proof document from disk.
5. Edit a line and undo/redo.
6. Add, edit, collapse, and delete an annotation.
7. Search within the current document.
8. Run manual region OCR on a small crop.
9. Export current page and selected pages.
10. Confirm generated export opens locally.
11. Confirm no source image is uploaded to external OCR services.

## Final Report Template

Use this structure when the final regression is actually executed:

```markdown
# GlowFish Audit Regression Report

Date:
Branch:
Start commit:
End commit:

## Summary

- Code changes:
- Docs changes:
- Deleted items:
- Behavior-impacting refactors:

## Automated Tests

| Suite | Command | Result | Notes |
|---|---|---|---|
| proofread full | ... | pass/fail/skipped | ... |
| license server | ... | pass/fail/skipped | ... |
| client licensing | ... | pass/fail/skipped | ... |
| OCR focus | ... | pass/fail/skipped | ... |
| export focus | ... | pass/fail/skipped | ... |
| frontend syntax | ... | pass/fail/skipped | ... |
| desktop selftest | ... | pass/fail/skipped | ... |

## Bench

| Engine | Dataset | F1 | Recall | Precision | CER | Gate | Result |
|---|---|---:|---:|---:|---:|---|---|

## Offline Boundary

- OCR upload path found:
- Model files complete:
- No-network smoke:
- Remaining offline risks:

## Known Warnings

- pytest default temp permission issue: use `--basetemp`
- Pillow `Image.Image.getdata` deprecation before Pillow 14 on 2027-10-15

## Residual Risks

- Printed-material gold set:
- Full PaddleOCR environment:
- Packaged app smoke:
- Account/member server track:
```

## Stop Conditions

Stop and investigate before further cleanup if any of these happens:

- OCR focus suite fails
- `ppocrv6_onnx` bench drops below F1 gate
- signing/canonicalization tests fail
- export tests fail after proof model changes
- frontend syntax checks fail
- any test failure points to source upload, model download dependency, or
  changed proof/export semantics
