# -*- coding: utf-8 -*-
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_static(name):
    return (ROOT / "src" / name).read_text(encoding="utf-8")


def test_text_undo_uses_timed_merge_helper():
    app = read_static("app.js")
    assert "const TEXT_UNDO_MERGE_MS = 800;" in app
    assert "let textUndoMerge = { scope: null, ts: 0 };" in app
    assert "function resetTextUndoMerge()" in app
    assert "function pushTextUndo(scopeKey)" in app
    assert "Date.now()" in app.split("function pushTextUndo(scopeKey)", 1)[1].split("function undo()", 1)[0]
    assert "resetTextUndoMerge();" in app.split("function pushUndo", 1)[1].split("function undo()", 1)[0]


def test_row_and_page_text_edits_use_timed_undo_scopes():
    editor = read_static("editor.js")
    page_block = editor.split("function renderPage()", 1)[1].split("function renderEditor()", 1)[0]
    assert "let snapped = false" not in editor
    assert 'pushTextUndo("row:" + id);' in editor
    assert 'pushTextUndo("page:" + page().page_id);' in editor
    enter_block = page_block.split('if (e.key === "Enter")', 1)[1].split('const active = document.activeElement;', 1)[0]
    assert 'pushTextUndo("page:" + page().page_id);' in enter_block


def test_annotation_text_edits_are_undoable_with_timed_scopes():
    annotations = read_static("annotations.js")
    assert 'pushTextUndo("annot:" + it.id);' in annotations
    assert 'pushTextUndo("page_annot:" + pg.page_id);' in annotations


def test_structural_undo_operations_reset_text_merge_window():
    editor = read_static("editor.js")
    viewer = read_static("viewer.js")
    annotations = read_static("annotations.js")
    for marker in ["function mergePrev", "function mergeWholeUp", "function splitNext", "function splitNewLine", "function insertPunct", "function doDelete", "function togglePara"]:
        block = editor.split(marker, 1)[1].split("pushUndo();", 1)[0]
        assert "resetTextUndoMerge();" in block
    assert "resetTextUndoMerge();" in viewer.split('/api/reocr_region', 1)[1].split("pushUndo();", 1)[0]
    assert "resetTextUndoMerge();" in annotations.split("function gfCreateAnnot", 1)[1].split("pushUndo();", 1)[0]
    assert "resetTextUndoMerge();" in annotations.split("del.addEventListener", 1)[1].split("pushUndo();", 1)[0]
