import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_json_documents_parse(self):
        for path in [
            ROOT / "schemas" / "proof.schema.v1.json",
            ROOT / "schemas" / "ocr.schema.v1.json",
            ROOT / "examples" / "proof.v1.json",
            ROOT / "examples" / "ocr.v1.json",
        ]:
            with self.subTest(path=path.name):
                self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_proof_example_preserves_three_text_layers(self):
        proof = json.loads((ROOT / "examples" / "proof.v1.json").read_text(encoding="utf-8"))
        line = proof["pages"][0]["lines"][0]
        self.assertTrue({"text_ocr", "text_draft", "text"}.issubset(line))
        self.assertIn("noise_lines", proof["pages"][0])
        self.assertIn("order", proof["pages"][0])

    def test_ocr_example_preserves_line_contract(self):
        result = json.loads((ROOT / "examples" / "ocr.v1.json").read_text(encoding="utf-8"))
        line = result["p001"]["lines"][0]
        self.assertEqual({"text", "box", "score"}, set(line))
        self.assertEqual(4, len(line["box"]))

    def test_openapi_documents_have_required_endpoints(self):
        host = (ROOT / "openapi" / "host.v1.yaml").read_text(encoding="utf-8")
        for endpoint in ["/health", "/api/me", "/api/open", "/api/import_progress",
                         "/api/import_jobs/recoverable", "/api/import_jobs/{job_id}/resume",
                         "/api/import_jobs/{job_id}", "/api/save", "/api/reocr_region", "/api/export"]:
            self.assertIn(endpoint + ":", host)

    def test_recovery_types_are_exported(self):
        from glowfish_contracts import OcrProgress, RecoverableOcrJob

        self.assertIn("completed_by_engine", OcrProgress.__annotations__)
        self.assertEqual(
            {"job_id", "batch", "source", "completed", "total", "engine", "updated_at", "failed_pages"},
            RecoverableOcrJob.__required_keys__,
        )


if __name__ == "__main__":
    unittest.main()
