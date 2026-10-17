from pathlib import Path


SOURCE = (Path(__file__).parents[1] / "src" / "importer.js").read_text(encoding="utf-8")


def test_import_waits_for_first_page_and_registers_document_before_open():
    block = SOURCE.split("async function confirmImportOnce()", 1)[1]
    register_at = block.index("nbRegisterProofDoc(metaProof")
    open_at = block.index("await applyLoaded(data)")
    stop_at = block.index("stopImportProgress()")
    assert register_at < open_at < stop_at


def test_import_open_failure_is_separate_from_ocr_failure_and_is_caught():
    block = SOURCE.split("async function confirmImportOnce()", 1)[1]
    assert "let fail = 0;" in block
    assert "let openFail = 0;" in block
    assert "openFail++;" in block
    assert "\\u5bfc\\u5165\\u5df2\\u5b8c\\u6210" in block
    assert "\\u53ef\\u4ece\\u5de6\\u4fa7\\u91cd\\u65b0\\u6253\\u5f00" in block


def test_import_busy_state_wraps_backend_and_first_page_open():
    block = SOURCE.split("async function confirmImportOnce()", 1)[1]
    busy_at = block.index('gfSetDocumentBusy("import", true)')
    open_at = block.index("await applyLoaded(data)")
    idle_at = block.index('gfSetDocumentBusy("import", false)')
    stop_at = block.index("stopImportProgress()")
    assert busy_at < open_at < idle_at < stop_at
