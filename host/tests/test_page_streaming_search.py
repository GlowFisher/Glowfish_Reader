import json

import document_repository
import library_api


class SearchContext:
    def __init__(self, work):
        self.work = work
        self.notebooks_path = work / "notebooks.json"


def test_legacy_and_current_search_routes_share_page_iterator(tmp_path, monkeypatch):
    batch = "large search document"
    directory = tmp_path / batch
    directory.mkdir()
    pages = [
        {
            "page_id": f"page-{index + 1}",
            "lines": [{"id": f"line-{index}", "text": f"needle text {index}"}],
            "order": [f"line-{index}"],
        }
        for index in range(500)
    ]
    (directory / "proof.json").write_text(
        json.dumps({"batch": batch, "pages": pages}), encoding="utf-8"
    )
    context = SearchContext(tmp_path)
    context.notebooks_path.write_text(
        json.dumps({"documents": {batch: {"displayName": "Large"}}}), encoding="utf-8"
    )

    def reject_full_load(_self):
        raise AssertionError("search must not load a complete document")

    monkeypatch.setattr(document_repository.DocumentRepository, "load_full", reject_full_load)
    result = library_api._paged_library_search(context, {"query": "needle", "limit": 200})

    assert len(result["hits"]) == 200
    assert result["truncated"] is True
    assert result["hits"][0]["pageId"] == "page-1"
    assert result["hits"][-1]["pageId"] == "page-200"
