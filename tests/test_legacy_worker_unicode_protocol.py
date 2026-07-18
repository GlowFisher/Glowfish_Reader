from pathlib import Path


PROOFREAD = (
    Path(__file__).resolve().parents[1] / "glowfish_reader" / "proofread"
)


def test_legacy_rollback_workers_escape_unicode_request_paths():
    for name in ("recognize_ppocrv6.py", "recognize_ppocrv6_onnx.py"):
        text = (PROOFREAD / name).read_text(encoding="utf-8")

        assert "json.dumps(job, ensure_ascii=True)" in text
        assert "json.dumps(config, ensure_ascii=True)" in text
        assert "json.dumps(job, ensure_ascii=False)" not in text
