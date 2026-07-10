from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parent


def read_static(name):
    return (ROOT / "static" / name).read_text(encoding="utf-8")


def read_app(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_core_static_javascript_is_parseable():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available")
    for name in ("importer.js", "notebook.js"):
        result = subprocess.run(
            [node, "--check", str(ROOT / "static" / name)],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_noise_button_removed_and_region_toggle_button_added():
    html = read_static("index.html")
    assert 'id="noiseToggle"' not in html
    assert 'id="boxToggle"' in html


def test_boxes_hidden_by_default_and_region_ocr_does_not_require_toggle():
    settings = read_static("settings.js")
    viewer = read_static("viewer.js")
    css = read_static("style.css")
    assert "show_boxes: false" in settings
    assert '"show_boxes": False' in read_app("settings_store.py")
    # 框选只由 #boxToggle 按钮开的模式驱动（按钮文案即契约），Alt 不是快捷键。
    assert "if (regionSelectMode && !eraseMode)" in viewer
    assert "e.altKey && boxesVisible()" not in viewer
    assert '$("#imgWrap").appendChild(selEl)' in viewer
    assert "body.hide-boxes #boxes" in css
    assert "body.region-select-mode #left" in css
    assert "gf-boxes-hidden-v3" in settings


def test_region_toggle_has_hover_guidance():
    html = read_static("index.html")
    assert 'id="boxToggle"' in html
    assert '>识</button>' in html
    assert '进入框选识别模式' in html
    assert '直接在底图上拖出区域重新识别' in html
    assert 'title=' in html

def test_zoom_percent_is_first_item_in_canvas_toolbar():
    html = read_static("index.html")
    zoom_ctl = html.split('<div id="zoomCtl">', 1)[1].split("</div>", 1)[0]
    assert zoom_ctl.index('id="zoomPct"') < zoom_ctl.index('id="zoomReset"')
    assert zoom_ctl.index('id="zoomReset"') < zoom_ctl.index('id="zoomIn"')
    assert zoom_ctl.index('id="zoomIn"') < zoom_ctl.index('id="zoomOut"')
    assert zoom_ctl.index('id="zoomOut"') < zoom_ctl.index('id="boxToggle"')


def test_box_erase_button_sits_after_region_toggle():
    html = read_static("index.html")
    zoom_ctl = html.split('<div id="zoomCtl">', 1)[1].split("</div>", 1)[0]
    assert 'id="boxErase"' in zoom_ctl
    assert zoom_ctl.index('id="boxToggle"') < zoom_ctl.index('id="boxErase"')
    erase_attrs = zoom_ctl.split('id="boxErase"', 1)[1].split(">", 1)[0]
    assert 'hidden' in erase_attrs
    assert 'hidden' in erase_attrs.split('class="', 1)[1].split('"', 1)[0].split()
    erase_button = zoom_ctl.split('id="boxErase"', 1)[1].split("</button>", 1)[0]
    assert 'aria-label="橡皮擦"' in erase_button
    assert "<svg" in erase_button
    assert ">擦" not in erase_button


def test_box_erase_mode_visibility_and_click_behavior_are_wired():
    viewer = read_static("viewer.js")
    assert "let eraseMode = false" in viewer
    assert "function setEraseMode(on)" in viewer
    assert '$("#boxErase").onclick = toggleEraseMode;' in viewer
    assert 'eraseMode && !item.noise' in viewer
    assert "doDelete(l.id)" in viewer
    assert "activateRow(l.id)" in viewer
    assert viewer.index("doDelete(l.id)") < viewer.index("activateRow(l.id)")
    sync_block = viewer.split("function syncBoxToggle()", 1)[1].split("function setRegionSelectMode(on)", 1)[0]
    assert "erase.hidden = !on" in sync_block
    assert 'erase.classList.toggle("hidden", !on)' in sync_block
    assert "setEraseMode(false)" in sync_block
    toggle_erase_block = viewer.split("function toggleEraseMode()", 1)[1].split("function setRegionSelectMode(on)", 1)[0]
    assert "settings.show_boxes" not in toggle_erase_block
    assert "let regionSelectMode = false" in viewer
    assert "function toggleRegionSelectMode()" in viewer
    assert "if (regionSelectMode && !eraseMode)" in viewer
    assert "eraseMode && e.altKey" in viewer          # 擦除模式下 Alt 拖拽不得起框选
    # 擦除是框选模式的子模式：onclick 里必须先判 eraseMode，否则 regionSelectMode 的
    # 提前 return 会让擦除分支永远走不到（2026-07-08 修的「擦除失效」）。
    assert viewer.index("eraseMode && !item.noise") < viewer.index("if (regionSelectMode) return;")


def test_region_ocr_shows_top_bar_busy_status_while_request_runs():
    html = read_static("index.html")
    viewer = read_static("viewer.js")
    css = read_static("style.css")
    guofeng = read_static("guofeng.css")
    assert 'id="regionOcrStatus"' in html
    assert 'id="regionOcrStatus"' in html and 'aria-live="polite"' in html
    blank_area = html.split('<span id="importFail"', 1)[1].split('<span class="bar-spacer"', 1)[0]
    right_group = html.split('<span id="rightGroup">', 1)[1].split('<button id="layoutBtn"', 1)[0]
    assert 'id="regionOcrStatus"' in blank_area
    assert 'id="regionOcrStatus"' not in right_group
    assert "function setRegionOcrBusy" in viewer
    assert 'setRegionOcrBusy(true);' in viewer
    assert "requestAnimationFrame" in viewer
    assert 'setRegionOcrBusy(false);' in viewer
    assert "finally" in viewer
    assert viewer.index('setRegionOcrBusy(true);') < viewer.index('/api/reocr_region')
    assert "#regionOcrStatus" in css
    assert "#regionOcrStatus { flex: 0 0 auto;" in css
    assert "#regionOcrStatus:not(.hidden)::before" in guofeng

def test_selected_page_export_collects_tree_documents_when_current_notebook_is_missing():
    notebook = read_static("notebook.js")
    assert "function nbExportTreeDocIds" in notebook
    assert "Object.keys(nbTree.documents || {})" in notebook
    assert "nbExportTreeDocIds()" in notebook


def test_selected_page_export_uses_file_checkboxes_without_page_rows():
    notebook = read_static("notebook.js")
    css = read_static("notebook.css")
    assert "nbExportPageRows" not in notebook
    assert ".nb-page-row" not in css
    assert ".nb-export-doc-check" in css

def test_notebook_bulk_delete_mode_reuses_file_checkboxes():
    notebook = read_static("notebook.js")
    css = read_static("notebook.css")
    assert "nbDeletePickMode" in notebook
    assert "function nbStartDeleteDocSelect" in notebook
    assert "function nbConfirmDeleteSelectedDocs" in notebook
    assert "nb-pick-doc-check" in css
    assert ".nb-delete-bar" in css


def test_notebook_nav_long_names_do_not_force_sidebar_width():
    css = read_static("notebook.css")
    nb_nav_rule = css.split("#nbNav {", 1)[1].split("}", 1)[0]
    nb_tree_rule = css.split("#nbTree {", 1)[1].split("}", 1)[0]
    nb_row_rule = css.split(".nb-row {", 1)[1].split("}", 1)[0]
    nb_name_rule = css.split(".nb-name {", 1)[1].split("}", 1)[0]
    nb_doc_rule = css.split(".nb-doc {", 1)[1].split("}", 1)[0]
    assert "min-width: 0" in nb_nav_rule
    assert "overflow: hidden" in nb_nav_rule
    assert "min-width: 0" in nb_tree_rule
    assert "overflow-x: hidden" in nb_tree_rule
    assert "min-width: 0" in nb_row_rule
    assert "min-width: 0" in nb_name_rule
    assert "min-width: 0" in nb_doc_rule

def test_annotation_panel_does_not_show_highlight_kind_label():
    js = read_static("annotations.js")
    html = read_static("index.html")
    assert "highlight kind" not in js.lower()
    assert "data-kind" not in html

def test_image_load_failure_has_user_visible_toast():
    app = read_static("app.js")
    assert "img.onerror" in app
    assert "/img/" in app
    assert "原图" in app


def test_cached_document_open_prefers_disk_load_before_indexeddb_fallback():
    notebook = read_static("notebook.js")
    disk_first = 'loaded = await api("/api/load?batch=" + encodeURIComponent(id))'
    cache_fallback = 'applyLoaded({ proof: rec.proof'
    assert disk_first in notebook
    assert cache_fallback in notebook
    assert notebook.index(disk_first) < notebook.index(cache_fallback)

def test_collapsed_annotation_panel_shrinks_to_count_badge():
    notebook = read_static("notebook.css")
    guofeng = read_static("guofeng.css")
    assert "#annotPanel.ann-collapsed { display: inline-flex; width: fit-content !important; min-width: 0 !important; height: auto; min-height: 0;" in notebook
    assert "#annotPanel.ann-collapsed #annBar { display: inline-flex; flex: 0 0 auto; width: fit-content; min-width: 0; padding: 6px 7px 6px 10px; gap: 6px;" in notebook
    assert "#annotPanel.ann-collapsed .ann-title { flex: 0 0 auto;" in notebook
    assert "#annotPanel.ann-collapsed .ann-cnt { flex: 0 0 auto;" in notebook
    collapsed_skin = guofeng.split("#annotPanel.ann-collapsed", 1)[1].split("#annotPanel.ann-collapsed:hover", 1)[0]
    assert "width:" not in collapsed_skin
    assert "height:" not in collapsed_skin
    assert "min-width:" not in collapsed_skin
    assert "min-height:" not in collapsed_skin
def test_vertical_row_proofreading_spacing_is_more_compact():
    editor = read_static("editor.js")
    css = read_static("style.css")
    guofeng = read_static("guofeng.css")
    theme = read_static("theme.css")
    assert ".vcol::before" not in css
    assert "pg.order.forEach((id, idx) =>" in editor
    assert '<span class="vidx">${idx + 1}</span>' in editor
    assert "#vlines { position: relative; display: flex; flex-direction: row; direction: rtl; align-items: flex-start;" in css
    assert "--v-text-col: calc(var(--txt-size, 16px) * 1.95);" in css
    assert "--v-col-step: clamp(44px, calc(var(--v-text-col) + 1.05vw), 68px);" in css
    assert "--v-col-step: 56px" not in css
    assert "width: max-content; min-width: 100%;" in css
    assert "width: max-content; min-width: 100%; min-height: 100%;" not in css
    assert "box-sizing: border-box; padding: 0 2px 8px;" in css
    assert "gap: 10px" not in css.split("#vlines", 1)[1].split(".vcol", 1)[0]
    assert "min-height: 100%; padding: 5px 2px;" not in css
    assert "background-image" not in css.split("#vlines", 1)[1].split(".vcol", 1)[0]
    assert ".vcol { direction: ltr; flex: 0 0 var(--v-col-step); display: flex; flex-direction: column; align-items: center; gap: 3px;" in css
    assert "width: var(--v-col-step); min-width: var(--v-col-step); max-width: var(--v-col-step);" not in css
    assert "width: var(--v-col-step); min-width: var(--v-col-step);" in css
    assert "min-height: 100%; box-sizing: border-box; border-left: 1px solid var(--zhu-line, #efd5c8); padding: 0;" not in css
    assert "box-sizing: border-box; border-left: 1px solid var(--zhu-line, #efd5c8); padding: 5px 4px;" in css
    assert ".vcol { border-left-color: var(--zhu-line); }" in guofeng
    assert ".vcol.para { box-shadow: inset 2px 0 0 var(--brand); }" in css
    assert ".vbody { display: flex; flex: 0 0 auto; min-height: 0; flex-direction: row; align-items: flex-start; justify-content: center; gap: clamp(2px, .22vw, 6px); width: 100%; }" in css
    assert ".v-ops { display: flex; flex-direction: column; gap: 5px; }" in css
    assert ".vidx { flex: 0 0 auto; color: var(--brand); opacity: .75; font-size: 12px; line-height: 1; font-family: ui-monospace, Consolas, monospace; padding-top: 7px; }" in css
    assert ".v-txt { writing-mode: vertical-rl; text-orientation: upright;" in css
    assert "width: var(--v-text-col); min-width: var(--v-text-col); max-width: var(--v-text-col); margin: 0 auto;" in css
    assert "height: max-content; min-height: 100%;" not in css
    assert "height: auto; min-height: 1.45em; box-sizing: border-box; padding: 3px 0; border: 1px solid transparent;" in css
    assert "white-space: nowrap; overflow: visible; overflow-wrap: normal; word-break: keep-all;" in css
    assert "width: 2.2em; min-width: 0; max-width: 100%; margin: 0 auto;" not in css
    vtxt_rule = css.split(".v-txt { writing-mode", 1)[1].split("}", 1)[0]
    assert "white-space: nowrap" in vtxt_rule
    assert "max-width: 100%" not in vtxt_rule
    assert "background-image" not in vtxt_rule
    assert "background-size" not in vtxt_rule
    assert "background-origin" not in vtxt_rule
    assert "--v-line-step" not in vtxt_rule
    assert "50%" not in vtxt_rule
    assert "body.gf-dark .v-txt { background-image:" not in theme
    assert ".txt, .v-txt { border-color: transparent; background-color: transparent; }" in guofeng
    assert ".txt, .v-txt { border-color: transparent; background: transparent; }" not in guofeng
    assert ".txt:focus, .v-txt:focus { border-color: var(--brand); box-shadow: 0 0 0 1px var(--brand); background-color: #fffdf6; }" in guofeng
    assert ".txt:focus, .v-txt:focus { border-color: var(--brand); box-shadow: 0 0 0 1px var(--brand); background: #fffdf6; }" not in guofeng
    assert "body.gf-dark .txt, body.gf-dark .v-txt, body.gf-dark #searchInput" not in theme
    assert "body.gf-dark .txt:focus, body.gf-dark .v-txt:focus { background: #211d16; }" not in theme
    assert "body.gf-dark .txt:focus, body.gf-dark .v-txt:focus { background-color: #211d16; }" in theme
    assert "body.gf-dark .idx, body.gf-dark .vidx { color: var(--brand); opacity: .8; }" in theme
    assert "line-height: 1.55" in css

def test_row_proofreading_spacing_is_more_compact():
    css = read_static("style.css")
    assert ".row { display: flex; align-items: flex-start; gap: 6px; padding: 5px 4px;" in css
    assert "line-height: 1.55" in css
def test_page_proofreading_rules_share_line_step_without_offset():
    editor = read_static("editor.js")
    notebook = read_static("notebook.css")
    guofeng = read_static("guofeng.css")
    theme = read_static("theme.css")
    assert "page-text-vertical" not in editor
    assert "page-text-vertical" not in notebook
    assert "page-text-vertical" not in guofeng
    assert "page-text-vertical" not in theme
    assert 'div.id = "pageText"; div.className = "page-text";' in editor
    assert "page-line-offset" not in guofeng
    assert "background-position: 0 var(--page-line-offset)" not in guofeng
    assert "--page-line-step: 2.15em" in guofeng
    assert "background-size: 100% var(--page-line-step)" in guofeng
    assert "body.gf-dark .page-text { background-color: #211d16; color: var(--ink); border-color: var(--line); }" in theme
    assert "body.gf-dark .txt, body.gf-dark .v-txt, body.gf-dark #searchInput, body.gf-dark .page-text" not in theme
    assert "page-line-offset" not in theme
    assert "--page-line-step:" not in theme


def test_page_proofreading_enter_keeps_manual_line_breaks():
    editor = read_static("editor.js")
    page_block = editor.split("function renderPage()", 1)[1].split("function renderEditor()", 1)[0]
    assert 'const nv = div.textContent;' in page_block
    assert '.replace(/\\n/g, "")' not in page_block
    assert 'const nv = cur.slice(0, at) + "\\n" + cur.slice(at);' in page_block
    assert 'applyPageText(nv);' in page_block
    assert 'setCaret(div, at + 1);' in page_block
    assert 'document.execCommand("insertText", false, "\\n");' not in page_block
    assert 'if (e.key === "Enter") { e.preventDefault(); return; }' not in page_block

def test_proof_mode_bar_stays_outside_horizontal_scroll():
    notebook = read_static("notebook.css")
    css = read_static("style.css")
    assert "#proofModeBar { position: sticky; top: 0; z-index: 30;" in notebook
    assert "#searchPanel { position: fixed; top: 52px; right: 14px; z-index: 120;" in notebook
    proof_bar = notebook.split("#proofModeBar {", 1)[1].split("}", 1)[0]
    assert "linear-gradient" not in proof_bar
    assert ".pm-seg { display: inline-flex; background: var(--paper, #f8f3e8);" in notebook
    assert "box-shadow: 0 4px 14px rgba(28, 40, 56, .12);" in notebook
    assert "width: calc(100vw - var(--right-pad-x" not in notebook
    assert "#right { flex: 1; min-height: 0; overflow: hidden;" in css
    assert "display: flex; flex-direction: column; --right-pad-x: 16px;" in css
    assert "#editorBody { flex: 1 1 auto; min-width: 0; min-height: 0; overflow: auto; }" in css
    assert '#editorBody[data-layout="vertical"][data-proof-mode="row"] { padding-bottom: 10px; }' not in css
    assert "#vlines" in css and "direction: rtl" in css.split("#vlines", 1)[1].split("}", 1)[0]
    assert "width: calc(100vw - var(--right-pad-x" not in css

def test_top_bar_popovers_stay_above_proof_mode_bar():
    css = read_static("style.css")
    notebook = read_static("notebook.css")
    guofeng = read_static("guofeng.css")
    theme = read_static("theme.css")

    bar_rule = css.split("#bar {", 1)[1].split("}", 1)[0]
    assert "position: relative" in bar_rule
    assert "z-index: 100" in bar_rule

    proof_bar = notebook.split("#proofModeBar {", 1)[1].split("}", 1)[0]
    assert "z-index: 30" in proof_bar
    assert "pointer-events: none" in proof_bar
    assert "background: transparent" in proof_bar
    pm_seg = notebook.split(".pm-seg {", 1)[1].split("}", 1)[0]
    assert "pointer-events: auto" in pm_seg

    search_panel = notebook.split("#searchPanel {", 1)[1].split("}", 1)[0]
    assert "z-index: 120" in search_panel
    assert "z-index: 120" in css.split(".account-menu {", 1)[1].split("}", 1)[0]
    assert "z-index: 120" in css.split("#exportMenu.bar-menu {", 1)[1].split("}", 1)[0]

    assert "#proofModeBar { background:" not in guofeng
    assert "body.gf-dark #proofModeBar { background:" not in theme
def test_engine_pref_click_persists_immediately():
    settings = read_static("settings.js")
    assert 'if (b.dataset.key === "engine_pref") persistEnginePreference();' in settings
    assert "function persistEnginePreference()" in settings
    assert "JSON.stringify({ engine_pref: settings.engine_pref || \"\" })" in settings
    assert "toast(" in settings


def test_importer_supports_display_name_rename_before_import():
    importer = read_static("importer.js")
    assert "imp-name-input" in importer
    assert "function commitImportItemName" in importer
    assert "function renameImportItem" not in importer
    assert "imp-rename" not in importer
    assert 'prompt("' not in importer.split("function renderImporter()", 1)[1].split("function initImporter", 1)[0]
    row_block = importer.split("function renderImporter()", 1)[1].split("function expandPdf", 1)[0]
    assert 'value="${impEsc(it.name)}"' in row_block
    assert "imp-name-input" in row_block
    assert row_block.index("imp-name-input") < row_block.index("imp-del")
    assert "it.name = name;" in importer
    confirm_block = importer.split("async function confirmImport()", 1)[1]
    assert 'groups.push({ name: stem(it.name), items: [{ rel: it.rel, type: "image" }] });' in confirm_block
    assert 'groups.push({ name: stem(it.name), items: [] });' in confirm_block


def test_notebook_file_inline_rename_without_path_changes():
    notebook = read_static("notebook.js")
    css = read_static("notebook.css")
    assert 'class: "btn nb-doc-del"' in notebook
    assert 'nbEl("input", { class: "nb-doc-name"' in notebook
    assert "readonly: true" in notebook
    assert "nb-doc-name-input" not in notebook
    assert "let nbDocClickTimer" in notebook
    assert '.addEventListener("dblclick"' in notebook
    assert "clearTimeout(nbDocClickTimer)" in notebook
    assert "nbStartDocNameEdit(nameInput, d.id)" in notebook
    assert 'e.target.closest(".nb-doc-name")' in notebook
    assert "setTimeout(() => nbOpenDoc(d.id), 220)" in notebook
    assert 'removeAttribute("readonly")' in notebook
    assert 'classList.add("editing")' in notebook
    assert 'classList.remove("editing")' in notebook
    assert ".focus()" in notebook
    assert ".select()" in notebook
    assert "contextmenu" not in notebook
    assert "function nbDocMenu" not in notebook
    assert "function nbRenameDoc" in notebook
    name_rule = css.split(".nb-doc-name {", 1)[1].split("}", 1)[0]
    assert "border: 1px solid transparent" in name_rule
    assert "background: transparent" in name_rule
    assert ".nb-doc-name.editing" in css
    rename_block = notebook.split("function nbRenameDoc", 1)[1].split("// ", 1)[0]
    assert "meta.displayName = name;" in rename_block
    assert "proof.batch === docId" in rename_block
    assert "proof.source = name;" in rename_block
    assert 'api("/api/save"' in rename_block
    assert "gfCacheProof()" in rename_block
    assert 'nbAskDelete("doc"' in notebook




