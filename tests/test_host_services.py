import json

from glowfish_host.services import DocumentService, OcrProgressStore


def test_document_roundtrip_is_lossless(tmp_path):
    proof = {"pages": [{"lines": [{"text_ocr": "原", "text_draft": "稿", "text": "定"}]}]}
    path = tmp_path / "proof.json"
    DocumentService().save(path, proof)
    assert DocumentService().load(path) == proof


def test_progress_store_returns_copies():
    store = OcrProgressStore()
    store.put("one", {"done": 1})
    value = store.get("one")
    value["done"] = 9
    assert store.get("one")["done"] == 1
    assert store.cancel("one")
