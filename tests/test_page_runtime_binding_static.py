from pathlib import Path


ROOT = Path(__file__).parents[1] / "src"


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_legacy_app_no_longer_owns_page_or_script_controls():
    app = read("app.js")
    assert "function pageNext()" not in app
    assert "function pagePrev()" not in app
    assert "async function toggleScript()" not in app
    assert 'bindClick("nextPage", pageNext)' not in app
    assert 'bindClick("prevPage", pagePrev)' not in app
    assert 'bindClick("scriptBtn", toggleScript)' not in app


def test_page_runtime_owns_all_three_control_bindings():
    runtime = read("app-page-runtime.js")
    assert 'bindClick("nextPage", pageNext)' in runtime
    assert 'bindClick("prevPage", pagePrev)' in runtime
    assert 'bindClick("scriptBtn", toggleScript)' in runtime


def test_runtime_load_order_and_cache_versions_are_pinned():
    html = read("index.html")
    app_tag = '<script src="app.js?v=20260723-page-runtime-binding"></script>'
    runtime_tag = '<script src="app-page-runtime.js?v=20260723-page-runtime-binding"></script>'
    assert app_tag in html
    assert runtime_tag in html
    assert html.index(app_tag) < html.index(runtime_tag)
