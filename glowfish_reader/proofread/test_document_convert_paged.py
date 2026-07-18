import json

from content_api import _convert_document_pages
from document_repository import repository_for_proof


def test_document_conversion_commits_one_page_at_a_time(tmp_path):
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps({
        "batch": "batch", "script": "s",
        "pages": [
            {"page_id": "p1", "lines": [{"id": "p1_1", "text": "alpha"}], "order": ["p1_1"]},
            {"page_id": "p2", "lines": [{"id": "p2_1", "text": "beta"}], "order": ["p2_1"]},
        ],
    }), encoding="utf-8")
    repo = repository_for_proof(proof_path)

    meta = _convert_document_pages(repo, "t")

    assert meta["script"] == "t"
    assert repo.load_page("p1")["revision"] == 1
    assert repo.load_page("p2")["revision"] == 1
    assert proof_path.is_file()  # Compatibility snapshot remains available.
