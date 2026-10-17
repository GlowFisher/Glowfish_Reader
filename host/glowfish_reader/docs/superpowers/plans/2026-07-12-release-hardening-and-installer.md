# Glowfish Reader Release Hardening and Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a Windows setup installer that refuses to ship unless the frozen application, including real offline OCR, has passed repeatable checks.

**Architecture:** Keep the existing PyInstaller `onedir` design and Inno Setup installer. Add a small runtime logging layer and a real OCR self-test to the frozen executable; make `release.ps1` execute both as mandatory gates before Inno Setup. Package the WebView2 offline Evergreen runtime so the desktop shell does not depend on a preinstalled browser runtime or Internet access.

**Tech Stack:** Python 3.12, PyInstaller 6.21, FastAPI, PyWebView/WebView2, PaddleOCR 3.7 ONNX Runtime 1.27, Inno Setup 6, PowerShell 5.1+.

## Global Constraints

- Preserve the current `single` SKU: it uses the existing cloud account registration/login gate while keeping document data under the local user storage root.
- OCR self-test must load only bundled PP-OCRv6 ONNX models; it must not download a model or require Python, Conda, Paddle, or an OCR cache installed on the machine.
- Any failed build gate stops before `ISCC.exe` runs.
- Tests must run with an explicit project-local `--basetemp`, never the permission-denied default Windows pytest cache path.
- Do not delete user data in `%APPDATA%\Glowfish Reader 史料阅读器` during install, upgrade, test, or uninstall.

---

### Task 1: Add durable frozen-app and OCR diagnostics

**Files:**
- Create: `proofread/runtime_logging.py`
- Modify: `proofread/desktop_app.py:16-264`
- Test: `proofread/test_runtime_logging.py`

**Interfaces:**
- `runtime_logging.configure_runtime_logging(mode: str) -> pathlib.Path` creates `<data_root>/logs`, configures UTF-8 rotating logs, and returns the active log file.
- `runtime_logging.log_exception(exc_type, exc, tb) -> None` records uncaught exceptions.
- `desktop_app` calls `configure_runtime_logging("gui")` before server/WebView imports and `configure_runtime_logging("ocr")` before OCR-child dispatch.

- [ ] **Step 1: Write failing tests for UTF-8 logs and traceback capture.**

```python
def test_configure_runtime_logging_writes_under_data_root(monkeypatch, tmp_path):
    monkeypatch.setattr(appconfig, "data_root", lambda: tmp_path)
    path = runtime_logging.configure_runtime_logging("ocr")
    logging.getLogger("release-test").error("OCR diagnostic")
    assert path.parent == tmp_path / "logs"
    assert "OCR diagnostic" in path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the test and confirm it fails because `runtime_logging` does not exist.**

Run:

```powershell
..\.venv\Scripts\python.exe -m pytest -q test_runtime_logging.py --basetemp .pytest_tmp_release
```

Expected: collection failure for `runtime_logging`.

- [ ] **Step 3: Implement the logging module.**

```python
def configure_runtime_logging(mode: str) -> Path:
    log_dir = appconfig.data_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{mode}.log"
    handler = RotatingFileHandler(path, encoding="utf-8", maxBytes=2_000_000, backupCount=5)
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    sys.excepthook = log_exception
    return path
```

Use `logging.exception()` in `log_exception`; never log passwords, SMS codes, session cookies, or full document text.

- [ ] **Step 4: Wire it into `desktop_app.py`.**

Call the OCR mode setup at the start of `_run_ocr_child()` and GUI mode setup immediately after `_harden_std()`. Replace silent `except Exception: pass` in `_prewarm_async()` and the top-level GUI failure handler with `logging.exception(...)`, while retaining the existing user-facing native error window.

- [ ] **Step 5: Run focused tests and commit.**

```powershell
..\.venv\Scripts\python.exe -m pytest -q test_runtime_logging.py test_desktop_ocr_dispatch.py --basetemp .pytest_tmp_release
git add proofread/runtime_logging.py proofread/desktop_app.py proofread/test_runtime_logging.py
git commit -m "fix: persist desktop and OCR runtime diagnostics"
```

### Task 2: Add a real, offline OCR self-test to the frozen executable

**Files:**
- Create: `proofread/assets/selftest/ocr_smoke.png` (copy the small deterministic fixture now at `bench/fixtures/vertical_cht_clean.png`)
- Modify: `proofread/glowfish_reader.spec:51-55`
- Modify: `proofread/desktop_app.py:118-152,255-259`
- Create: `proofread/test_desktop_ocr_selftest.py`

**Interfaces:**
- `desktop_app._selftest_ocr() -> int` returns `0` only when bundled model construction, one-image OCR, JSON creation, and at least one recognized line all succeed.
- CLI `glowfish_reader.exe --selftest-ocr` must not create user batches or make network requests.

- [ ] **Step 1: Write failing self-test unit tests.**

```python
def test_selftest_ocr_accepts_nonempty_bundled_result(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop_app.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    monkeypatch.setattr(recognize_ppocrv6_onnx, "_build_engine", lambda config: object())
    monkeypatch.setattr(recognize_ppocrv6_onnx, "run_job", lambda *a, **k: (1, 0))
    # Write a JSON object containing one page with one line from the run_job stub.
    assert desktop_app._selftest_ocr() == 0
```

Add companion cases for missing fixture, build exception, missing output JSON, and zero lines; every case must return `1` and write an error to `logs/ocr.log`.

- [ ] **Step 2: Run the new tests and confirm failure.**

```powershell
..\.venv\Scripts\python.exe -m pytest -q test_desktop_ocr_selftest.py --basetemp .pytest_tmp_release
```

- [ ] **Step 3: Bundle the fixture and implement `_selftest_ocr`.**

Add this to `glowfish_reader.spec`:

```python
datas += [(os.path.join(HERE, "assets", "selftest"), os.path.join("assets", "selftest"))]
```

In `_selftest_ocr`, locate `HERE / "assets" / "selftest" / "ocr_smoke.png"`, create a `tempfile.TemporaryDirectory`, call `recognize_ppocrv6_onnx._build_engine({"text_det_limit_side_len": 960, "text_det_limit_type": "max"})`, call `run_job`, parse the generated JSON, and require `pages == 1`, `failed == 0`, and `sum(len(page["lines"]) for page in result.values()) >= 1`. Print exactly `SELFTEST OCR OK` on success and `SELFTEST OCR FAIL: <reason>` on failure.

- [ ] **Step 4: Register the CLI before GUI startup.**

```python
if arg1 == "--selftest-ocr":
    sys.exit(_selftest_ocr())
```

Place it adjacent to `--selftest` and `--selftest-capabilities` so it never opens PyWebView.

- [ ] **Step 5: Verify source and frozen behavior.**

```powershell
..\.venv\Scripts\python.exe -m pytest -q test_desktop_ocr_selftest.py test_capabilities.py --basetemp .pytest_tmp_release
..\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm glowfish_reader.spec
$p = Start-Process .\dist\glowfish_reader\glowfish_reader.exe -ArgumentList '--selftest-ocr' -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "frozen OCR self-test failed: $($p.ExitCode)" }
```

- [ ] **Step 6: Commit.**

```powershell
git add proofread/assets/selftest/ocr_smoke.png proofread/glowfish_reader.spec proofread/desktop_app.py proofread/test_desktop_ocr_selftest.py
git commit -m "test: gate releases on frozen offline OCR"
```

### Task 3: Reconcile the three failing regression tests with the shipped OCR behavior

**Files:**
- Modify: `proofread/test_det_scale.py:48-56,106-110`
- Modify: `proofread/test_ppocrv6_engine.py:78-86`
- Inspect only: `proofread/det_scale.py`, `proofread/engines.py`, OCR benchmark reports under `bench/out/`

- [ ] **Step 1: Confirm the intended behavior from the current implementation and benchmark record.**

`det_scale.py` intentionally uses `PITCH_MIN=60` and `PITCH_MAX=120`; it no longer exposes `TARGET_PITCH` or `SHUPAI_DET_TARGET_PITCH`. `engines.py` deliberately passes `column_rescue=True` for the high-accuracy profile, and `recognize_ppocrv6_onnx.py` consumes the high profile.

- [ ] **Step 2: Update tests, not production code, unless benchmark evidence contradicts this design.**

Replace the obsolete target assertion with:

```python
assert 404 * scale == pytest.approx(det_scale.PITCH_MAX, abs=0.5)
```

Replace the environment test with:

```python
monkeypatch.setenv("SHUPAI_DET_PITCH_MAX", "100")
assert 404 * det_scale.scale_for(404.0) == pytest.approx(100.0, abs=0.5)
```

Replace the stale engine assertion with:

```python
assert params["column_rescue"] is True
```

- [ ] **Step 3: Run exact regressions and the full suite.**

```powershell
..\.venv\Scripts\python.exe -m pytest -q test_det_scale.py test_ppocrv6_engine.py --basetemp .pytest_tmp_release
..\.venv\Scripts\python.exe -m pytest -q --basetemp .pytest_tmp_release_full
```

Expected: no failing tests; the prior baseline was `325 passed, 3 failed, 1 skipped`.

- [ ] **Step 4: Commit.**

```powershell
git add proofread/test_det_scale.py proofread/test_ppocrv6_engine.py
git commit -m "test: align OCR regressions with current profile design"
```

### Task 4: Make the release script enforce all frozen checks

**Files:**
- Modify: `proofread/release.ps1:49-63`
- Create: `proofread/test_release_script_static.py`

- [ ] **Step 1: Write static tests for mandatory gate ordering.**

Assert the script contains `--selftest-capabilities`, `--selftest`, and `--selftest-ocr`, all using `Start-Process -Wait -PassThru`, and that `ISCC` resolution appears only after those gates.

- [ ] **Step 2: Add a helper that fails on a nonzero windowed-exe exit code.**

```powershell
function Invoke-FrozenGate([string]$Name, [string]$Argument) {
  $p = Start-Process -FilePath $frozenExe -ArgumentList $Argument -NoNewWindow -Wait -PassThru
  if ($p.ExitCode -ne 0) { throw "$Name FAILED ($($p.ExitCode)); see %APPDATA%\\Glowfish Reader 史料阅读器\\logs" }
  Write-Host "[release]   $Name OK"
}
```

Call it in this exact order: capabilities, service self-test, real OCR self-test. Delete the existing one-off capability block rather than leaving two paths.

- [ ] **Step 3: Run script tests and a non-upload release rehearsal.**

```powershell
..\.venv\Scripts\python.exe -m pytest -q test_release_script_static.py --basetemp .pytest_tmp_release
.\release.ps1 -Notes "release rehearsal; do not upload"
```

Expected: all three frozen checks pass before an installer is compiled; no `-Upload` flag is used.

- [ ] **Step 4: Commit.**

```powershell
git add proofread/release.ps1 proofread/test_release_script_static.py
git commit -m "build: require frozen OCR before installer compilation"
```

### Task 5: Bundle WebView2 and make missing-runtime failure explicit

**Files:**
- Add external binary: `proofread/vendor/MicrosoftEdgeWebView2RuntimeInstallerX64.exe`
- Create: `proofread/vendor/WEBVIEW2.sha256`
- Modify: `proofread/installer.iss:55-85`
- Modify: `proofread/release.ps1:38-49`
- Create: `proofread/test_installer_static.py`

- [ ] **Step 1: Obtain and verify the official x64 Evergreen Standalone Installer.**

Store it at the exact path above. Record the downloaded file's SHA-256 in `WEBVIEW2.sha256`. Use the standalone installer, not the online bootstrapper: clean acceptance machines may have no Internet connection.

- [ ] **Step 2: Make its absence a build failure in `release.ps1`.**

```powershell
$webViewInstaller = Join-Path $here "vendor\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
if (-not (Test-Path $webViewInstaller)) { throw "WebView2 offline runtime missing: $webViewInstaller" }
```

- [ ] **Step 3: Include and run it from Inno Setup.**

Replace the commented `[Files]` entry with:

```ini
Source: "vendor\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: WebView2Missing
```

Set `[Run]` to the matching filename and retain `waituntilterminated`. Add a `CurStepChanged(ssPostInstall)` message box only when `WebView2Missing()` is still true after the installer returns; text must tell users that the app needs WebView2 and give the log location.

- [ ] **Step 4: Verify installer-source gates.**

```powershell
..\.venv\Scripts\python.exe -m pytest -q test_installer_static.py --basetemp .pytest_tmp_release
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

Expected: the setup compiles only when the offline runtime exists.

- [ ] **Step 5: Commit.**

```powershell
git add proofread/vendor proofread/installer.iss proofread/release.ps1 proofread/test_installer_static.py
git commit -m "fix: include WebView2 offline runtime in setup"
```

### Task 6: Clean-machine release and acceptance runbook

**Files:**
- Create: `proofread/docs/RELEASE_RUNBOOK.md`
- Create: `proofread/docs/ACCEPTANCE_MATRIX.md`

- [ ] **Step 1: Define the clean build host.**

Use a new Windows 11 x64 VM snapshot with no project checkout, no Python, no Conda, no Paddle/PaddleX cache, and no prior Glowfish installation. Use Python `3.12.x`, create `.venv`, and install exactly:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r proofread\requirements-app.txt -r proofread\requirements-desktop.txt
```

- [ ] **Step 2: Build from a clean output state.**

Before building, archive—not delete—the prior artifacts outside the working tree. Then:

```powershell
Set-Location proofread
Remove-Item build,dist,Output -Recurse -Force
..\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm glowfish_reader.spec
.\release.ps1 -Notes "<versioned release notes>"
```

Do not pass `-Upload` in this stage.

- [ ] **Step 3: Run installation acceptance on a second clean VM.**

Install `Output\glowfish_reader_setup_<version>.exe`, then record pass/fail and screenshot/log paths for every row:

| Scenario | Pass condition |
|---|---|
| No Python/Conda/cache | App starts; both OCR profiles create nonempty results. |
| No WebView2 Runtime | Setup installs runtime; app opens normally. |
| Login/register | Cloud SMS registration, login, app restart, logout, and password reset work. |
| Offline OCR | Disconnect network after installation; imported PNG/JPG still recognizes. |
| PDF import | Imported PDF is converted/recognized without a developer tool. |
| Annotations/export | Annotation survives restart; DOCX export opens in Word. |
| Upgrade | New setup preserves `%APPDATA%` documents/settings. |
| Uninstall | Program files are removed; `%APPDATA%` documents/settings remain. |
| Paths | Chinese and >260-character input/output paths report a clear result, never a silent failure. |
| Network failure | Account/authorization UI shows an actionable message without exposing a stack trace. |

- [ ] **Step 4: Sign and publish only after the matrix is complete.**

Sign the installer and executable using the organization’s certificate, verify signatures with `Get-AuthenticodeSignature`, calculate SHA-256 with `Get-FileHash`, upload the versioned installer first, verify its CDN download/hash, and upload `update.json` last. Release to a limited tester group before public distribution.

## Self-Review

- OCR freeze diagnosis, persistent logs, real OCR gate, release-script gate, WebView2 packaging, clean build, installer acceptance, login registration, offline OCR, upgrade/uninstall, signing, hashes, and manifest-last publication are all covered by Tasks 1–6.
- The plan intentionally does not change the SKU because current `single` mode already enforces the cloud-account login gate.
- Each code task has a failing test, focused verification, and a commit boundary.
