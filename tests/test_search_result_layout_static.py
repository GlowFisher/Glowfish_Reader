# -*- coding: utf-8 -*-
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_static(name):
    return (ROOT / "src" / name).read_text(encoding="utf-8")


def test_search_result_long_document_names_are_ellipsized_without_hiding_snippets():
    css = read_static("notebook.css")
    search_js = read_static("search.js")

    hit_rule = css.split(".search-hit {", 1)[1].split("}", 1)[0]
    page_rule = css.split(".sh-page {", 1)[1].split("}", 1)[0]
    assert ".sh-doc-name {" in css
    doc_name_rule = css.split(".sh-doc-name {", 1)[1].split("}", 1)[0]
    assert ".sh-page-no {" in css
    page_no_rule = css.split(".sh-page-no {", 1)[1].split("}", 1)[0]
    snip_rule = css.split(".sh-snip {", 1)[1].split("}", 1)[0]

    assert "min-width: 0" in hit_rule
    assert "max-width: 42%" in page_rule
    assert "display: flex" in page_rule
    assert "flex: 1 1 auto" in doc_name_rule
    assert "min-width: 0" in doc_name_rule
    assert "white-space: nowrap" in doc_name_rule
    assert "overflow: hidden" in doc_name_rule
    assert "text-overflow: ellipsis" in doc_name_rule
    assert "white-space: nowrap" in page_no_rule
    assert "flex: 1 1 auto" in snip_rule
    assert "min-width: 0" in snip_rule
    assert "row.title = h.docName;" in search_js
    assert "sh-doc-name" in search_js
    assert "sh-page-no" in search_js