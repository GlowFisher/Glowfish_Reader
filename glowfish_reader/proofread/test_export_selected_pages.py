# -*- coding: utf-8 -*-
from pathlib import Path

from export_api import _export_single


ROOT = Path(__file__).resolve().parent


def read_static(name):
    return (ROOT / "static" / name).read_text(encoding="utf-8")


def _proof():
    def page(pid, text):
        return {
            "page_id": pid,
            "image": "",
            "lines": [{"id": pid + "__1", "text": text, "deleted": False, "para_break": False}],
            "order": [pid + "__1"],
        }

    return {
        "batch": "sample",
        "script": "s",
        "pages": [
            page("p1", "first page text"),
            page("p2", "second page text"),
            page("p3", "third page text"),
        ],
    }


class _Ctx:
    def reg(self, _batch):
        return None


def test_selected_pages_scope_exports_only_requested_pages():
    response = _export_single(
        _Ctx(),
        {"scope": "selected_pages", "proof": _proof(), "page_ids": ["p3", "p1"]},
        "txt",
        False,
    )

    body = response.body.decode("utf-8")

    assert "first page text" in body
    assert "third page text" in body
    assert "second page text" not in body
    assert response.headers["X-Doc-Paragraphs"] == "1"
    assert "sample_2%E9%A1%B5_%E8%BE%91%E5%BD%95.txt" in response.headers["Content-Disposition"]

def test_docx_with_image_returns_docx_not_zip():
    response = _export_single(
        _Ctx(),
        {"scope": "all", "proof": _proof()},
        "docx",
        True,
    )

    cd = response.headers["Content-Disposition"]
    assert ".docx" in cd
    assert ".zip" not in cd
    assert response.media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_markdown_with_image_still_returns_zip():
    response = _export_single(
        _Ctx(),
        {"scope": "all", "proof": _proof()},
        "md",
        True,
    )

    cd = response.headers["Content-Disposition"]
    assert ".zip" in cd
    assert response.media_type == "application/zip"

def test_frontend_selected_export_menu_is_wired_to_current_dom_ids():
    html = read_static("index.html")
    app = read_static("app.js")

    assert 'id="expSelect"' in html
    assert "expHere" not in app
    assert 'bindClick("expSelect", () => {' in app
    assert "nbStartExportPageSelect()" in app
    assert 'scope === "selected_pages"' in app
    assert "nbExportSelectedPayload()" in app
    assert "with_image: withImage" in app


def test_frontend_export_prefers_native_then_browser_save_picker_then_download():
    app = read_static("app.js")
    flow = app.split("async function downloadExport", 1)[1].split("async function selectedPagesExportBody", 1)[0]

    assert 'gfBridge("save_export")' in flow
    assert "browserSaveExport(fname, blob)" in flow
    assert 'document.createElement("a")' in flow
    assert flow.index('gfBridge("save_export")') < flow.index("browserSaveExport(fname, blob)")
    assert flow.index("browserSaveExport(fname, blob)") < flow.index('document.createElement("a")')
    assert "window.showSaveFilePicker" in app
    assert ".docx" in app
    assert ".txt" in app
    assert ".md" in app
    assert ".csv" in app
    assert ".zip" in app


def test_frontend_export_cancel_from_save_picker_is_silent():
    app = read_static("app.js")

    assert "AbortError" in app
    assert "canceled: true" in app
    assert "if (m.canceled) return;" in app
def test_export_route_selected_pages_uses_selected_payload_without_current_proof(tmp_path):
    import asyncio
    import json
    from export_api import export

    batch_dir = tmp_path / "batch_a"
    batch_dir.mkdir()
    (batch_dir / "proof.json").write_text(json.dumps(_proof()), encoding="utf-8")

    class Ctx:
        settings_path = tmp_path / "settings.json"

        def reg(self, batch):
            if batch == "batch_a":
                return {"proof_path": str(batch_dir / "proof.json")}
            return None

    class Req:
        async def json(self):
            return {
                "scope": "selected_pages",
                "selected": [{"batch": "batch_a", "page_ids": ["p3", "p1"]}],
                "name": "selection",
                "fmt": "txt",
                "with_image": False,
            }

    response = asyncio.run(export(Req(), Ctx()))
    body = response.body.decode("utf-8")

    assert "first page text" in body
    assert "third page text" in body
    assert "second page text" not in body
    assert response.headers["X-Doc-Paragraphs"] == "1"
