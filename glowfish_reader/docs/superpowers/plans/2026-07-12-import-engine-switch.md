# 导入弹窗引擎快捷切换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compact full/fast OCR engine switch to the import modal and synchronize it with the existing global engine preference.

**Architecture:** `settings.engine_pref` remains the source of truth. `index.html` supplies buttons, `settings.js` supplies shared persistence and synchronization, and `style.css` scopes smaller sizing to exactly five sorting buttons.

**Tech Stack:** HTML, CSS, vanilla JavaScript, Python pytest static-source tests.

## Global Constraints

- Engine values remain `""` and `"ppocrv6_onnx"`.
- Settings says `满血版 / 快速版`; the import modal says `满血 / 快速`.
- Do not alter OCR behavior, main toolbar, import file list, or import bottom actions.
- Reuse non-blocking `/api/settings` persistence.

---

### Task 1: Shared engine setting

**Files:**
- Create: `proofread/test_import_engine_switch_static.py`
- Modify: `proofread/test_settings_engine_labels.py`
- Modify: `proofread/static/settings.js`

**Interfaces:**
- Consumes: `settings.engine_pref`, `persistEnginePreference()`, `updateSegBtns()`.
- Produces: `setEnginePreference(value)` and `syncImportEngineSwitch()`.

- [ ] **Step 1: Write failing tests**

```python
def test_import_engine_switch_uses_global_preference():
    index = read_static("index.html")
    settings = read_static("settings.js")
    assert 'id="impEngineFull"' in index
    assert 'id="impEngineFast"' in index
    assert 'data-engine=""' in index
    assert 'data-engine="ppocrv6_onnx"' in index
    assert "function setEnginePreference(value)" in settings
    assert "function syncImportEngineSwitch()" in settings
```

Update label expectations to `满血版`, `快速版`, and absence of `轻量版`.

- [ ] **Step 2: Confirm red**

Run `..\\.venv\\Scripts\\python.exe -m pytest proofread\\test_settings_engine_labels.py proofread\\test_import_engine_switch_static.py -q`.

Expected: FAIL because the current label is `轻量版` and shared helpers do not exist.

- [ ] **Step 3: Implement minimal helpers**

```javascript
function syncImportEngineSwitch() {
  document.querySelectorAll("[data-engine]").forEach((button) =>
    button.classList.toggle("on", button.dataset.engine === (settings.engine_pref || "")));
}
function setEnginePreference(value) {
  settings.engine_pref = value || "";
  persistEnginePreference();
  updateSegBtns();
  syncImportEngineSwitch();
}
```

Use `setEnginePreference(v)` from Settings; sync after initial settings loading; bind import buttons in `initSettings()`.

- [ ] **Step 4: Confirm green**

Run `..\\.venv\\Scripts\\python.exe -m pytest proofread\\test_settings_engine_labels.py proofread\\test_import_engine_switch_static.py -q`.

Expected: PASS.

- [ ] **Step 5: Commit**

Stage only `proofread/static/settings.js`, `proofread/test_settings_engine_labels.py`, and `proofread/test_import_engine_switch_static.py`; commit message: `feat: synchronize import engine preference`.

### Task 2: Import-modal controls

**Files:**
- Modify: `proofread/static/index.html`
- Modify: `proofread/static/style.css`
- Modify: `proofread/test_import_engine_switch_static.py`

**Interfaces:**
- Consumes: Task 1 data-engine binding and synchronization helper.
- Produces: five `imp-sort-btn` controls followed by `imp-engine-switch`.

- [ ] **Step 1: Extend the failing test**

```python
def test_import_modal_only_compacts_sort_controls_and_places_switch_after_them():
    index = read_static("index.html")
    css = read_static("style.css")
    assert index.count('class="btn btn-sec imp-sort-btn"') == 5
    assert index.index('data-sort="reverse"') < index.index('id="impEngineFull"')
    assert '.imp-toolbar .imp-sort-btn' in css
    assert '.imp-engine-switch' in css
```

- [ ] **Step 2: Confirm red**

Run `..\\.venv\\Scripts\\python.exe -m pytest proofread\\test_import_engine_switch_static.py -q`.

Expected: FAIL because the dedicated sort styles and switch are missing.

- [ ] **Step 3: Implement markup and CSS**

Assign `imp-sort-btn` to exactly the five sorting buttons. Immediately after them add:

```html
<span class="imp-engine-switch" role="group" aria-label="识别引擎">
  <button id="impEngineFull" class="btn btn-seg" type="button" data-engine="" title="满血版质量优先，处理可能较慢">满血</button>
  <button id="impEngineFast" class="btn btn-seg" type="button" data-engine="ppocrv6_onnx" title="快速版速度优先，更适合低配机器">快速</button>
</span>
```

Replace generic `.imp-toolbar .btn-sec` sizing with `.imp-toolbar .imp-sort-btn` sizing. Add inline-flex styling for `.imp-engine-switch`. Do not change `.modal-actions`.

- [ ] **Step 4: Confirm green**

Run `..\\.venv\\Scripts\\python.exe -m pytest proofread\\test_import_engine_switch_static.py proofread\\test_settings_engine_labels.py -q`.

Expected: PASS.

- [ ] **Step 5: Commit**

Stage only `proofread/static/index.html`, `proofread/static/style.css`, and `proofread/test_import_engine_switch_static.py`; commit message: `feat: add import engine switch`.

### Task 3: Verify behavior and scope

**Files:**
- Verify: `proofread/static/index.html`, `proofread/static/style.css`, `proofread/static/settings.js`

- [ ] **Step 1: Run regression tests**

Run `..\\.venv\\Scripts\\python.exe -m pytest proofread\\test_settings_engine_labels.py proofread\\test_import_engine_switch_static.py proofread\\test_search_result_layout_static.py proofread\\test_text_undo_static.py -q`.

Expected: PASS with no failures.

- [ ] **Step 2: Verify browser**

Open the import modal. Confirm only five sort buttons are compact; `满血 / 快速` immediately follows; title tooltips match the spec; each choice synchronizes with Settings; and Settings changes appear when the modal is reopened.

- [ ] **Step 3: Inspect scope**

Run `git diff HEAD -- proofread/static/index.html proofread/static/style.css proofread/static/settings.js proofread/test_settings_engine_labels.py proofread/test_import_engine_switch_static.py`.

Expected: only requested UI, synchronization, and test changes; no import bottom actions or OCR implementation changes.
