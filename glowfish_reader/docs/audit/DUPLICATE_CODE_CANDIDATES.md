# Duplicate Code Candidates

Update date: 2026-07-07

This note records the read-only duplicate-helper and legacy-entry scan from the
code slimming audit. It is a candidate list, not a deletion plan.

## Scope

Scanned areas:

- `proofread/`
- `license_server/`
- `bench/`
- `pipeline/`
- `proofread/static/`

Signals used:

- duplicate Python function names
- utility-style private helpers
- legacy engine labels and aliases
- compatibility stubs
- frontend global functions and old entry comments

## Safe Direct Deletions

None found in this pass.

Every duplicate or legacy-looking item that survived this scan either has a
compatibility role, different semantics, or belongs near OCR/signing behavior
where the risk is too high for direct pruning.

## Keep As Compatibility Surface

### Frontend Drag Stub

`proofread/static/dnd.js` is intentionally still loaded by
`proofread/static/index.html` and called from `proofread/static/editor.js`.

It preserves `initRowDrag(rowEl, id)` as a no-op because row drag sorting was
disabled by product decision. Deleting the file or function would break the
existing editor call path unless `editor.js` and `index.html` are changed in the
same migration.

Classification: keep.

Verification before any future change:

```powershell
rg -n "initRowDrag|dnd\.js" proofread\static -g "*.js" -g "*.html"
node --check proofread\static\editor.js
node --check proofread\static\app.js
```

### Legacy `onnx` Engine Alias

`onnx` is not a dead engine value. It is a legacy configuration alias that maps
to `ppocrv6_onnx` through `proofread/engines.py`.

`proofread/static/settings.js` also migrates saved `settings.engine_pref ===
"onnx"` to `ppocrv6_onnx`, and `proofread/test_settings_engine_labels.py`
asserts this compatibility.

Classification: keep.

Verification before any future change:

```powershell
.\.venv\Scripts\python.exe -m pytest proofread\test_settings_engine_labels.py proofread\test_ppocrv6_engine.py -q
```

## Low-Risk Candidates

### Bench Normalization Closures

Files:

- `bench/eval_cer.py`
- `bench/analyze_hw_errors.py`

Both define local `_norm` closures around OpenCC conversion and punctuation
stripping. They are bench-only and conceptually similar, but each closure is
small and local to a reporting workflow.

Classification: low-risk candidate, but not worth changing unless bench
normalization grows again.

Equivalence checks:

```powershell
.\.venv\Scripts\python.exe bench\run_bench.py --engine ppocrv6_onnx --only 手写
.\.venv\Scripts\python.exe bench\analyze_hw_errors.py
```

## Completed Consolidations

### Environment Cleanup Helpers

Files:

- `proofread/subprocess_env.py`
- `proofread/content_api.py`
- `bench/run_bench.py`

The duplicate `_clean_env()` implementations in `proofread/content_api.py` and
`bench/run_bench.py` were consolidated in commit:

- `f628bddf refactor: share subprocess environment cleanup`

Both call sites now keep their local `_clean_env()` compatibility wrapper and
delegate to `subprocess_env.clean_subprocess_env()`.

Behavior locked by:

- `proofread/test_subprocess_env.py`

Verification recorded during the refactor:

```powershell
.\.venv\Scripts\python.exe -m pytest proofread\test_subprocess_env.py proofread\test_content_fallback.py proofread\test_ppocrv6_engine.py -q -p no:cacheprovider --basetemp .pytest_tmp_env_commit
.\.venv\Scripts\python.exe -m py_compile proofread\subprocess_env.py proofread\content_api.py bench\run_bench.py
.\.venv\Scripts\python.exe -m pytest proofread -q -p no:cacheprovider --basetemp .pytest_tmp_proofread_env_refactor
.\.venv\Scripts\python.exe bench\run_bench.py --engine ppocrv6_onnx --only 手写
```

Observed results:

- focus suite: `27 passed, 8 warnings`
- proofread full suite: `198 passed, 13 warnings`
- lightweight hand-written bench: `F1=0.967`, `CER=0.076`

Classification: complete.

## Medium-Risk Candidates

### Signing Canonicalization

Files:

- `proofread/licensing/envelope.py`
- `license_server/sign.py`

Both `_canon(d)` implementations use the same JSON canonicalization:
`sort_keys=True`, compact separators, `ensure_ascii=False`, UTF-8 bytes.

This is real duplication, but it sits on the client/server signing boundary.
Any consolidation must first lock a golden sample for:

- signing on the server
- verifying in the client
- verifying legacy trial/activation credentials
- rejecting malformed signatures

Classification: medium-risk candidate with protocol compatibility risk.

Equivalence checks:

```powershell
.\.venv\Scripts\python.exe -m pytest license_server\tests proofread\licensing\tests -q
```

## Not A Merge Candidate

### OCR Line Score Helpers

Files:

- `proofread/ocr_quality.py`
- `proofread/ocr_rescue.py`

Both expose `_line_score`, but their defaults differ by design:

- `ocr_quality._line_score()` defaults missing/invalid scores to `1.0`.
- `ocr_rescue._line_score()` defaults missing/invalid scores to `0.0`.

The first treats absent scores as usable during aggregate quality inspection.
The second is conservative during rescue dedupe and line preference.

Classification: do not merge unless the scoring contract is redesigned and
covered by OCR golden tests.

Equivalence checks before any future rewrite:

```powershell
.\.venv\Scripts\python.exe -m pytest proofread\test_ocr_quality.py proofread\test_content_fallback.py -q
.\.venv\Scripts\python.exe bench\run_bench.py --engine ppocrv6_onnx --only 手写
```

### OCR Engine Worker Duplication

Files:

- `proofread/recognize_ppocrv6.py`
- `proofread/recognize_ppocrv6_onnx.py`
- `proofread/recognize.py`

There is substantial duplicated structure across the full PaddleOCR path, the
ONNX lightweight path, and the legacy Paddle path: worker lifecycle, page
listing, event emission, bounding-box helpers, subprocess-serving shape, and
`recognize_one` / `run_job` / `serve_worker` style entry points.

This is the largest duplicate cluster, but it is in the highest-risk OCR
pipeline. The files represent different model runtimes and fallback behavior.
Do not merge them during routine cleanup.

Classification: high-risk, isolate-first only.

Equivalence checks before any future refactor:

```powershell
.\.venv\Scripts\python.exe -m pytest proofread\test_ppocrv6_engine.py proofread\test_content_fallback.py proofread\test_ocr_quality.py -q
.\.venv\Scripts\python.exe bench\run_bench.py --engine ppocrv6_onnx --only 手写
```

If the full PaddleOCR environment is available, also run the full engine bench
with the configured `SHUPAI_PADDLE_PY` interpreter.

## Expected Noise

Do not treat these as cleanup targets by name alone:

- repeated route names such as `activate`, `check`, `deactivate`, `trial`, and
  `health`
- test helper names and fake route clients
- CLI or bench `print()` output
- frontend globals used by script-tag loading
- compatibility comments around archived VL/GGUF and old engine names

## Recommended Order

1. Keep compatibility stubs and aliases unchanged.
2. Treat `_clean_env()` consolidation as complete; do not repeat it unless more
   subprocess launchers need the same contract.
3. Only document bench helper duplication unless a future bench rewrite needs a
   shared helper.
4. Leave OCR worker duplication for a dedicated high-risk refactor with full
   golden samples and bench coverage.
