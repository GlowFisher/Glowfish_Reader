# PaddleX Cache Device Failure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure Glowfish Reader can initialize PaddleX on Windows even when high drive letters are occupied, disconnected, or the user profile contains non-ASCII characters.

**Architecture:** Move cache-path selection into one focused helper owned by the OCR runtime and mirror that helper into the packaged Host compatibility runtime. The helper validates every candidate by creating the directory and round-tripping a temporary write probe, treats a non-zero `subst` exit as failure, cleans up unusable aliases, and falls back to the writable application data directory. Both OCR engines call the same helper before importing PaddleOCR.

**Tech Stack:** Python 3.12, pytest, Windows `subst`, PaddleOCR/PaddleX 3.7, PyInstaller 6.21, PowerShell 5.1+.

## Global Constraints

- Preserve the five-repository split: OCR owns inference behavior; Host owns desktop packaging.
- Do not modify UI, Account, or Contracts unless a failing regression proves it is necessary.
- Do not write cache data beside the installed executable.
- A cache path is accepted only after its directory can be created and a temporary probe file can be written and removed.
- A failed or unavailable drive alias must never be exported through `PADDLE_PDX_CACHE_HOME`.
- Keep explicit valid `PADDLE_PDX_CACHE_HOME` overrides working; replace only unusable overrides.

---

### Task 1: Canonical OCR cache selection

**Files:**
- Create: `ocr/src/glowfish_ocr/legacy/paddlex_cache.py`
- Create: `ocr/tests/test_paddlex_cache.py`
- Modify: `ocr/src/glowfish_ocr/legacy/recognize_ppocrv6.py`
- Modify: `ocr/src/glowfish_ocr/legacy/recognize_ppocrv6_onnx.py`

**Interfaces:**
- Consumes: `data_root: pathlib.Path`, a subprocess-compatible `runner`, and an environment mapping.
- Produces: `configure_paddlex_cache(data_root, *, environ=None, platform_name=None, runner=None, register_cleanup=None, ensure_directory=None) -> pathlib.Path`.

- [x] **Step 1: Write failing tests for failed aliases and invalid overrides.**

```python
def test_failed_subst_is_not_selected(tmp_path):
    env = {}
    calls = []
    result = configure_paddlex_cache(
        tmp_path / "用户",
        environ=env,
        platform_name="nt",
        runner=runner_that_fails_z_and_succeeds_y(calls),
        ensure_directory=record_directory_creation,
    )
    assert result == Path("Y:/paddlex_cache")
    assert env["PADDLE_PDX_CACHE_HOME"] == str(result)

def test_unusable_explicit_cache_falls_back_to_data_root(tmp_path):
    env = {"PADDLE_PDX_CACHE_HOME": "Z:/paddlex_cache"}
    result = configure_paddlex_cache(
        tmp_path,
        environ=env,
        platform_name="nt",
        ensure_directory=raise_only_for_z,
    )
    assert result == tmp_path / "paddlex_cache"
```

- [x] **Step 2: Run the tests and verify RED.**

Run: `..\.venv\Scripts\python.exe -m pytest -q ocr\tests\test_paddlex_cache.py`

Expected: collection/import failure because `glowfish_ocr.legacy.paddlex_cache` does not exist.

- [x] **Step 3: Implement validated cache selection and wire both engines to it.**

```python
def configure_paddlex_cache(data_root, *, environ=None, platform_name=None,
                            runner=None, register_cleanup=None,
                            ensure_directory=None):
    # Validate an explicit override first; if unusable, remove it.
    # Create data_root before invoking subst.
    # On non-ASCII Windows paths, accept an alias only when subst exits 0
    # and the aliased cache directory can be created.
    # Otherwise create and return data_root / "paddlex_cache".
```

- [x] **Step 4: Run OCR cache tests and the OCR suite.**

Run: `..\.venv\Scripts\python.exe -m pytest -q ocr\tests`

Expected: all tests pass.

### Task 2: Packaged Host runtime mirror and engine coverage

**Files:**
- Create: `host/glowfish_reader/proofread/paddlex_cache.py`
- Create: `host/tests/test_paddlex_cache.py`
- Modify: `host/glowfish_reader/proofread/recognize_ppocrv6.py`
- Modify: `host/glowfish_reader/proofread/recognize_ppocrv6_onnx.py`
- Modify: `host/glowfish_reader/proofread/glowfish_reader.spec`

**Interfaces:**
- Consumes: the same `configure_paddlex_cache(...)` contract as Task 1.
- Produces: identical cache initialization in the frozen ONNX engine and the diagnostic Paddle engine.

- [x] **Step 1: Mirror the failing cache tests into Host.**

Run: `.\.venv\Scripts\python.exe -m pytest -q host\tests\test_paddlex_cache.py`

Expected: RED because the Host helper is absent.

- [x] **Step 2: Mirror the reviewed helper and replace both duplicated `_ensure_paddlex_env` implementations.**

```python
def _ensure_paddlex_env():
    # retain existing PaddleX flags and thread caps
    return paddlex_cache.configure_paddlex_cache(appconfig.data_root())
```

- [x] **Step 3: Ensure PyInstaller includes the helper.**

Add `paddlex_cache` to the explicit local-module list in `glowfish_reader.spec` when the existing collection rules do not already include it.

- [x] **Step 4: Run Host tests and the original screenshot reproduction.**

Run: `.\.venv\Scripts\python.exe -m pytest -q host\tests host\glowfish_reader\proofread\test_desktop_ocr_dispatch.py host\glowfish_reader\proofread\test_desktop_ocr_selftest.py`

Expected: all tests pass, and a simulated `subst Z:` exit code 1 selects a verified fallback rather than `Z:\paddlex_cache`.

### Task 3: Product integration and client acceptance

**Files:**
- Modify: `workspace-manifest.json`
- Modify: submodule pointers `host`, `ocr`
- Create or update: versioned internal-validation installer metadata only if the release build completes.

**Interfaces:**
- Consumes: verified Host and OCR commits.
- Produces: a product workspace pinned to the fixed commits and a client build that passes frozen OCR initialization.

- [x] **Step 1: Commit the component changes on their feature branches and update the product manifest SHAs.**

- [x] **Step 2: Run product verification.**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File .\verify.ps1 -Full`

Expected: workspace, Host, OCR, UI, Account, and Contracts checks pass.

- [x] **Step 3: Build the installer.**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File .\build-release.ps1 -Notes "Fix PaddleX cache device initialization"`

Expected: PyInstaller and Inno Setup exit 0 and produce a version-consistent setup executable.

- [x] **Step 4: Run frozen client acceptance.**

Run the packaged executable with `--selftest`, `--selftest-capabilities`, `--selftest-ocr-deps`, and `--selftest-ocr`; then import a fixture from a Windows account/data path containing Chinese characters while `Z:` is simulated as unavailable.

Expected: no unhandled exception dialog, OCR worker becomes ready, import completes or returns a structured in-app error unrelated to cache-device initialization.
